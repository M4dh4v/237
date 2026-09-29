"""The two serialisation formats the sealed document travels in.

Neither of these touches a key. This module is pure bytes in, bytes out, and it
imports nothing from :mod:`logfirst` -- so it can be tested without liboqs, and
so it cannot take part in an import cycle with :mod:`logfirst.crypto`.

There are two formats because there are two layers, and they are worth keeping
apart:

**The payload frame** is what gets *encrypted*. A document is not one thing: it
is the canonical text, which is what the linguistic watermark is a transformation
*of*, and it is the PDF that was actually distributed. Both have to survive the
round trip, and one of them is binary, so the plaintext is a small
length-prefixed frame rather than the raw text or a JSON-with-base64 envelope.
Base64 would inflate the PDF by a third before encryption and hand binary data to
a text parser.

**The container** is the file a person downloads -- ``DOC-0000.lfdoc``. It is the
encrypted frame, with an unencrypted header in front of it describing what the
file is. Raw ciphertext rather than hex, so the download is the size of the
sealed bytes rather than twice it.

Two properties of the container header have to be said out loud, because both
look like bugs and neither is one:

* **It carries ``key_envelope``, and that is deliberate.** That value is the
  content key wrapped to the authority's KEM *public* key. Publishing it is the
  point: anyone may hold it, and only the authority -- which holds the matching
  private key -- can unwrap it. Its presence is what makes the container a
  complete description of itself rather than something that only makes sense
  next to the server's database.
* **The header is not authenticated.** The AEAD's additional data here is only
  the ``doc_id``, so anything in the header that is not the doc id -- the
  classification, the page count, the pdf hash -- can be edited by anyone holding
  the file. Tampering with ``doc_id``, ``nonce``, ``ciphertext`` or
  ``key_envelope`` does break decryption, but the descriptive fields do not.
  So the header is a *label*: :func:`compare` exists to check it against the
  manifest that travelled *inside* the encryption, and a reader who has not done
  that has not learned anything the file's author could not have written.

The one thing the header does leak is the approximate size of the text and the
PDF, via the section table. That is the same class of leak as a document hash,
and it is stated here rather than left for someone to notice.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys

__all__ = [
    "PAYLOAD_MAGIC", "CONTAINER_MAGIC", "SECTION_NAMES", "SealedError",
    "frame", "unframe", "pack", "unpack", "describe", "compare", "section_table",
]

# Magic strings carry a version byte rather than a separate version field, so a
# reader that does not understand a file says so at the first eight bytes instead
# of after parsing a structure whose layout it may already have got wrong.
PAYLOAD_MAGIC = b"LFPAY\x00\x01"
CONTAINER_MAGIC = b"LFDOC\x00\x01"

FRAME_NAME = "LFPAY/1"
CONTAINER_NAME = "lfdoc"

# The frame's section names, in the order they must appear. A fixed, ordered set
# rather than a free-form map: an unknown section is an error, not something to
# skip, because silently ignoring part of a document is how a reader ends up
# verifying a hash of something other than what it was handed. A new section is
# a new frame version, and the magic says which.
SECTION_MANIFEST = "manifest"
SECTION_TEXT = "text"
SECTION_PDF = "pdf"
SECTION_NAMES = (SECTION_MANIFEST, SECTION_TEXT, SECTION_PDF)

# Every field the header and the manifest both carry, and which therefore has to
# agree. Kept as one list so :func:`compare` cannot drift from what is written.
AGREED_FIELDS = ("doc_id", "classification", "doc_hash", "pdf_hash", "font",
                 "pages", "created")

_MAX_SECTIONS = 32
_MAX_HEADER = 1 << 20          # a header is a description, not a document
_MAX_SECTION = (1 << 32) - 1   # the length field is 32 bits, so this is a bound
                               # on the format rather than a policy choice


class SealedError(ValueError):
    """A frame or container that cannot be trusted to mean what it says."""


# --------------------------------------------------------------------------
# The payload frame: what gets encrypted
# --------------------------------------------------------------------------

def frame(sections: dict[str, bytes]) -> bytes:
    """Pack named sections into the plaintext that will be sealed.

    The manifest is not treated as just another section: it must be present, and
    it must be first, so a reader has the authenticated description of the
    payload before it has to decide how to treat the rest of it.
    """
    unknown = set(sections) - set(SECTION_NAMES)
    if unknown:
        raise SealedError(f"unknown frame sections: {sorted(unknown)}")
    if SECTION_MANIFEST not in sections:
        raise SealedError("a frame must carry a manifest section")
    if SECTION_TEXT not in sections:
        raise SealedError("a frame must carry a text section")

    out = bytearray(PAYLOAD_MAGIC)
    ordered = [n for n in SECTION_NAMES if n in sections]
    out += struct.pack(">H", len(ordered))
    for name in ordered:
        data = sections[name]
        if not isinstance(data, (bytes, bytearray)):
            raise SealedError(f"section {name!r} is "
                              f"{type(data).__name__}, not bytes")
        if len(data) > _MAX_SECTION:
            raise SealedError(f"section {name!r} is too large to frame")
        encoded = name.encode("ascii")
        out += struct.pack(">B", len(encoded))
        out += encoded
        out += struct.pack(">I", len(data))
        out += data
    return bytes(out)


def unframe(blob: bytes) -> dict[str, bytes]:
    """Unpack a frame, refusing anything that does not fit exactly.

    Every failure here is a raise rather than a best-effort read. A frame whose
    last section is cut short would otherwise yield a *shorter document* than the
    one that was sealed, and since the watermark is embedded in and recovered
    from that text, a short read corrupts the evidence rather than merely losing
    some of it.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise SealedError(f"a frame is bytes, not {type(blob).__name__}")
    if not blob.startswith(PAYLOAD_MAGIC):
        raise SealedError("not a payload frame (bad magic or unknown version)")

    pos = len(PAYLOAD_MAGIC)
    if len(blob) < pos + 2:
        raise SealedError("frame ends before its section count")
    (count,) = struct.unpack_from(">H", blob, pos)
    pos += 2
    if count == 0 or count > _MAX_SECTIONS:
        raise SealedError(f"frame declares {count} sections")

    sections: dict[str, bytes] = {}
    order: list[str] = []
    for _ in range(count):
        if len(blob) < pos + 1:
            raise SealedError("frame ends inside a section header")
        (name_len,) = struct.unpack_from(">B", blob, pos)
        pos += 1
        if len(blob) < pos + name_len + 4:
            raise SealedError("frame ends inside a section name")
        try:
            name = blob[pos:pos + name_len].decode("ascii")
        except UnicodeDecodeError as e:
            raise SealedError("section name is not ASCII") from e
        pos += name_len
        if name not in SECTION_NAMES:
            raise SealedError(f"unknown frame section {name!r}")
        if name in sections:
            raise SealedError(f"duplicate frame section {name!r}")
        (length,) = struct.unpack_from(">I", blob, pos)
        pos += 4
        if len(blob) < pos + length:
            raise SealedError(
                f"section {name!r} declares {length} bytes but the frame ends "
                f"{pos + length - len(blob)} bytes short")
        sections[name] = bytes(blob[pos:pos + length])
        order.append(name)
        pos += length

    if order != [n for n in SECTION_NAMES if n in sections]:
        raise SealedError(f"frame sections are out of order: {order}")
    if pos != len(blob):
        raise SealedError(f"frame has {len(blob) - pos} trailing bytes")
    return sections


# --------------------------------------------------------------------------
# The container: the file that gets downloaded
# --------------------------------------------------------------------------

def _section_table(sections: dict[str, bytes]) -> list[dict]:
    """Describe the frame's contents without revealing any of them.

    Lets a reader say what is in the file -- one text, one PDF, this big -- while
    holding no key. The sizes are the leak noted in the module docstring.
    """
    return [{"name": n, "length": len(sections[n]),
             "sha256": hashlib.sha256(sections[n]).hexdigest()}
            for n in SECTION_NAMES if n in sections]


def section_table(manifest_bytes: bytes, text: bytes, pdf: bytes) -> list[dict]:
    """The section table for a payload built from these three parts."""
    return _section_table({SECTION_MANIFEST: manifest_bytes,
                           SECTION_TEXT: text, SECTION_PDF: pdf})


def pack(package: dict) -> bytes:
    """Serialise a sealed package into the downloadable container.

    ``package`` is the dict :func:`logfirst.crypto.ca.encrypt_framed_payload`
    returned: the header is everything in it except the ciphertext, and the
    ciphertext is written as raw bytes rather than the hex the package carries.
    """
    try:
        ciphertext = bytes.fromhex(package["ciphertext"])
    except (KeyError, TypeError, ValueError) as e:
        # TypeError is in the list because a None ciphertext is a plausible way
        # for this to be wrong, and it is not a ValueError.
        raise SealedError("package has no usable ciphertext") from e

    header = {k: v for k, v in package.items() if k != "ciphertext"}
    header["container"] = CONTAINER_NAME
    header["container_version"] = 1
    header.setdefault("frame", FRAME_NAME)

    body = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_HEADER:
        raise SealedError("container header is implausibly large")
    return CONTAINER_MAGIC + struct.pack(">I", len(body)) + body + ciphertext


def unpack(blob: bytes) -> dict:
    """Return ``{"header": dict, "ciphertext": bytes}``, or raise.

    The length is checked against the buffer rather than trusted, so a truncated
    download is an error here instead of a short ciphertext handed to the AEAD --
    which would fail the tag anyway, but with a message about authentication
    rather than about a truncated file, and the two call for different actions.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise SealedError(f"a container is bytes, not {type(blob).__name__}")
    if not blob.startswith(CONTAINER_MAGIC):
        raise SealedError("not a .lfdoc container (bad magic or unknown version)")
    pos = len(CONTAINER_MAGIC)
    if len(blob) < pos + 4:
        raise SealedError("container ends before its header length")
    (header_len,) = struct.unpack_from(">I", blob, pos)
    pos += 4
    if header_len > _MAX_HEADER:
        raise SealedError(f"container declares a {header_len}-byte header")
    if len(blob) < pos + header_len:
        raise SealedError("container ends inside its header")
    try:
        header = json.loads(blob[pos:pos + header_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SealedError(f"container header is not JSON: {e}") from e
    if not isinstance(header, dict):
        raise SealedError("container header is not an object")
    pos += header_len
    return {"header": header, "ciphertext": bytes(blob[pos:])}


def describe(blob: bytes) -> dict:
    """The container's public description, with no key and no decryption.

    This is what a reader can know before asking the authority for anything.
    :func:`compare` is how much of it they should believe.
    """
    return unpack(blob)["header"]


def compare(header: dict, manifest: dict) -> list[str]:
    """Fields where the container's label disagrees with the sealed manifest.

    The header is unauthenticated and the manifest is inside the AEAD, so when
    they disagree the manifest is the one to believe -- and the disagreement
    itself is the finding: somebody edited the label on the outside of the
    envelope. Returns the offending field names, empty when they agree.

    A field absent from both is not a disagreement; a field present in one and
    absent from the other is, because that is one side declining to be checked.
    """
    bad = []
    for field in AGREED_FIELDS:
        in_header, in_manifest = field in header, field in manifest
        if in_header != in_manifest:
            bad.append(field)
        elif in_header and header[field] != manifest[field]:
            bad.append(field)
    return bad


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "describe":
        print("usage: python -m logfirst.sealed describe FILE.lfdoc",
              file=sys.stderr)
        return 2
    blob = open(argv[1], "rb").read()
    try:
        header = describe(blob)
    except SealedError as e:
        print(f"{argv[1]}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(header, indent=2, sort_keys=True))
    print(f"\n{len(blob)} bytes. The header above is unauthenticated and the "
          f"ciphertext is not shown;\nno plaintext and no content key are "
          f"present in this file.", file=sys.stderr)
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
