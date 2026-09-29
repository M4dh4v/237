"""The sealed document's two formats, and the three claims made about them.

The claim the user actually asked for is the blunt one: **the downloaded PDF
must only open through the server**. That decomposes into things a test can
check without taking anyone's word for it:

* the ``.lfdoc`` file is *not* a PDF, and contains no PDF and no prose;
* its ciphertext is useless without the authority's KEM private key;
* the file a reader downloads is byte-for-byte the file the authority decrypts.

The last one is worth stating carefully, because it is the difference between a
demo and a magic trick. The browser downloads an envelope at distribution time;
the open happens later and travels a different path (the client sends a signed
request, the authority answers with the ciphertext from its own store). If those
two were different bytes, the file on disk would be decoration. They are the
same bytes, and the test that says so compares the container's ciphertext
against the receipt the open actually returned.

Everything here works on real sealed packages rather than hand-built
dictionaries. A fixture that fabricated a package could agree with the parser
about a format that nothing produces.
"""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone

import pytest

pytest.importorskip("oqs")

from logfirst import pdfdoc, sealed                                  # noqa: E402
from logfirst.crypto import aead, ca, onetime, pqc                   # noqa: E402

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)

# A string that appears in the document and nowhere else. If it survives into
# the container, the container is leaking plaintext, and a search for a word
# that is genuinely unique is the only version of that test that means anything.
MARKER = "zorblat-9184-quixotic-marker"

DOC = (
    "The quarterly logistics annex is circulated for review. " * 40
    + MARKER + " "
    + "Distribution is restricted to named recipients. " * 40
)


@pytest.fixture(scope="module")
def sealed_doc() -> dict:
    """A real sealed package, its content key, and its container."""
    kem_pub, kem_sec = pqc.kem_keypair(pqc.KEM)
    rendered = pdfdoc.render(DOC, doc_id="DOC-0000", classification="SECRET",
                             created=CREATED)
    package = ca.encrypt_framed_payload(
        DOC, rendered.data, "DOC-0000", "SECRET", kem_pub,
        extra_manifest={"created": CREATED.isoformat(),
                        "font": rendered.font, "pages": rendered.pages})
    return {
        "package": package,
        "key": onetime.unseal_content_key(kem_sec, package["key_envelope"]),
        "container": sealed.pack(package),
        "pdf": rendered.data,
        "kem_pub": kem_pub,
    }


# ==========================================================================
# The frame
# ==========================================================================

def test_a_frame_round_trips_its_sections():
    sections = {sealed.SECTION_MANIFEST: b'{"a":1}',
                sealed.SECTION_TEXT: "plain text".encode(),
                sealed.SECTION_PDF: bytes(range(256))}
    assert sealed.unframe(sealed.frame(sections)) == sections


def test_a_frame_carries_binary_sections_unchanged():
    """Not incidental: the PDF is binary, and a codec that only survived text
    would corrupt it in a way that still parsed."""
    blob = bytes(range(256)) * 4
    out = sealed.unframe(sealed.frame({sealed.SECTION_MANIFEST: b"{}",
                                       sealed.SECTION_TEXT: b"x",
                                       sealed.SECTION_PDF: blob}))
    assert out[sealed.SECTION_PDF] == blob


def test_a_frame_may_omit_the_pdf_but_not_the_manifest_or_text():
    ok = {sealed.SECTION_MANIFEST: b"{}", sealed.SECTION_TEXT: b"x"}
    assert sealed.unframe(sealed.frame(ok)) == ok
    for missing in (sealed.SECTION_MANIFEST, sealed.SECTION_TEXT):
        partial = {k: v for k, v in ok.items() if k != missing}
        with pytest.raises(sealed.SealedError, match="must carry"):
            sealed.frame(partial)


def test_an_unknown_section_is_refused_rather_than_skipped():
    """Skipping it would mean verifying a hash over less than the whole
    payload -- which is how a document gets replaced by a prefix of itself."""
    with pytest.raises(sealed.SealedError, match="unknown frame section"):
        sealed.frame({sealed.SECTION_MANIFEST: b"{}",
                      sealed.SECTION_TEXT: b"x", "thumbnail": b"..."})


def test_a_section_that_runs_past_the_end_is_an_error_not_a_short_read():
    """The failure this prevents is specific: a truncated frame would yield a
    *shorter document*, and the watermark is recovered from that text."""
    blob = bytearray(sealed.frame({sealed.SECTION_MANIFEST: b"{}",
                                   sealed.SECTION_TEXT: b"abcdefgh"}))
    # Rewrite the text section's length so it claims more than is present.
    blob[-12:-8] = struct.pack(">I", 999)
    with pytest.raises(sealed.SealedError, match="short"):
        sealed.unframe(bytes(blob))


def test_trailing_bytes_are_refused():
    blob = sealed.frame({sealed.SECTION_MANIFEST: b"{}",
                         sealed.SECTION_TEXT: b"x"}) + b"junk"
    with pytest.raises(sealed.SealedError, match="trailing"):
        sealed.unframe(blob)


def test_a_frame_that_is_not_a_frame_is_refused():
    for blob in (b"", b"not a frame at all", b"LFPAY\x00\x02" + b"\x00\x01"):
        with pytest.raises(sealed.SealedError):
            sealed.unframe(blob)


# ==========================================================================
# The container, and the claim the user made
# ==========================================================================

def test_the_container_is_not_a_pdf_and_carries_none(sealed_doc):
    """The literal requirement: the downloaded file must be locked.

    Asserted on the bytes rather than on the extension, because an extension is
    a name and this is about content. ``%PDF`` is the header every PDF reader
    looks for; if it is absent, no reader will open the file, whatever it is
    called.
    """
    blob = sealed_doc["container"]
    assert not blob.startswith(b"%PDF")
    assert b"%PDF" not in blob
    # The sealed PDF really does start with that, so the absence above is a
    # property of the container and not of a PDF that never had a header.
    assert sealed_doc["pdf"].startswith(b"%PDF")


def test_the_container_carries_no_prose(sealed_doc):
    blob = sealed_doc["container"]
    assert MARKER.encode() not in blob
    assert b"quarterly logistics annex" not in blob


def test_the_container_round_trips_to_the_package_it_came_from(sealed_doc):
    out = sealed.unpack(sealed_doc["container"])
    assert out["ciphertext"] == bytes.fromhex(sealed_doc["package"]["ciphertext"])
    header = out["header"]
    assert header["doc_id"] == "DOC-0000"
    assert header["classification"] == "SECRET"
    assert header["container"] == "lfdoc"


def test_the_header_publishes_the_wrapped_key_and_that_is_the_point(sealed_doc):
    """``key_envelope`` is in the clear on purpose.

    Publishing it is what makes the container a complete description of itself:
    a reader holds the wrapped key and still cannot use it, because unwrapping
    needs the authority's private half. This test asserts both halves of that --
    it is present, and it is not the key.
    """
    header = sealed.describe(sealed_doc["container"])
    assert header["key_envelope"]
    assert sealed_doc["key"].hex() not in json.dumps(header)


def test_without_the_authoritys_private_key_the_container_stays_shut(sealed_doc):
    """A stranger's keypair is what an attacker has, and it does not even yield a
    candidate key: decapsulating the published envelope with the wrong ML-KEM
    secret produces a wrong shared secret, so the AEAD over the wrapped content
    key fails its tag before anything downstream is reached.

    This is the whole reason the container is safe to hand out. It carries the
    locked box and the lock; the key is elsewhere.
    """
    _, other_sec = pqc.kem_keypair(pqc.KEM)
    header = sealed.describe(sealed_doc["container"])
    with pytest.raises(Exception):
        onetime.unseal_content_key(other_sec, header["key_envelope"])


def test_a_guessed_content_key_does_not_open_the_payload(sealed_doc):
    """And if someone skipped the envelope and simply guessed 32 bytes, the
    document's own AEAD tag refuses it."""
    with pytest.raises(Exception):
        ca.open_payload(dict(sealed_doc["package"]), b"\x00" * 32)


def test_describe_shows_the_header_and_none_of_the_ciphertext(sealed_doc):
    header = sealed.describe(sealed_doc["container"])
    assert "ciphertext" not in header
    assert header["sections"], "the header should describe what is inside"
    assert {s["name"] for s in header["sections"]} == {"manifest", "text", "pdf"}


def test_a_truncated_or_mislabelled_container_is_refused():
    for blob in (b"", b"LFDOC\x00\x02" + b"\x00\x00\x00\x02{}"):
        with pytest.raises(sealed.SealedError):
            sealed.unpack(blob)


def test_a_container_header_that_lies_about_its_length_is_refused():
    blob = bytearray(sealed.CONTAINER_MAGIC + struct.pack(">I", 1 << 30))
    blob += b"{}"
    with pytest.raises(sealed.SealedError, match="header"):
        sealed.unpack(bytes(blob))


def test_packing_something_that_is_not_a_package_is_refused():
    for bad in ({}, {"ciphertext": "not hex"}, {"ciphertext": None}):
        with pytest.raises(sealed.SealedError):
            sealed.pack(bad)


# ==========================================================================
# The header is a label, and compare() is how you stop believing it
# ==========================================================================

def test_the_header_is_unauthenticated_and_compare_is_what_catches_it(sealed_doc):
    """Editing the header does not break decryption, and it should not pretend
    to. The AEAD binds only the doc id, so a header that has been rewritten is
    still a header that opens -- which is exactly why the manifest travels
    inside the encryption and the two are compared after."""
    header = dict(sealed.describe(sealed_doc["container"]))
    header["classification"] = "UNCLASSIFIED"
    header["pages"] = 1
    body = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    forged = sealed.CONTAINER_MAGIC + struct.pack(">I", len(body)) + body \
        + bytes.fromhex(sealed_doc["package"]["ciphertext"])

    # The lie survives inspection on its own...
    assert sealed.describe(forged)["classification"] == "UNCLASSIFIED"

    # ...and is caught the moment the label is held against the manifest that
    # was sealed.
    payload = ca.open_payload(sealed_doc["package"], sealed_doc["key"])
    assert sealed.compare(sealed.describe(forged), payload["manifest"]) == \
        ["classification"]


def test_an_honest_header_compares_clean(sealed_doc):
    payload = ca.open_payload(sealed_doc["package"], sealed_doc["key"])
    assert sealed.compare(sealed.describe(sealed_doc["container"]),
                          payload["manifest"]) == []


# ==========================================================================
# The payload's own integrity
# ==========================================================================

def test_the_payload_returns_the_text_and_the_pdf_that_were_sealed(sealed_doc):
    out = ca.open_payload(sealed_doc["package"], sealed_doc["key"])
    assert out["text"] == DOC
    assert out["pdf"] == sealed_doc["pdf"]
    assert out["manifest"]["pages"] == 1


def test_decrypt_document_still_returns_text(sealed_doc):
    """Its signature and its return type are load-bearing: the client, the
    aligner and existing tests all call it expecting prose."""
    assert ca.decrypt_document(sealed_doc["package"], sealed_doc["key"]) == DOC


def test_the_doc_hash_is_the_hash_of_the_text_not_of_the_envelope(sealed_doc):
    """Kept deliberately: ``doc_hash`` is a stored field the demo displays as a
    content hash, and redefining it to cover the frame would silently change
    what it means."""
    import hashlib

    assert sealed_doc["package"]["doc_hash"] == \
        hashlib.sha256(DOC.encode()).hexdigest()
    assert ca.verify_document_hash(sealed_doc["package"], DOC)


def test_a_payload_whose_text_does_not_match_its_hash_is_refused(sealed_doc):
    """The manifest is inside the AEAD, so this cannot be reached by tampering
    with a file -- it is the check that the frame is internally consistent, and
    it is asserted directly because a reader is entitled to know it is done."""
    package = dict(sealed_doc["package"])
    payload = ca.open_payload(package, sealed_doc["key"])
    manifest = dict(payload["manifest"])
    manifest["doc_hash"] = "0" * 64
    broken = sealed.frame({sealed.SECTION_MANIFEST:
                           json.dumps(manifest, sort_keys=True,
                                      separators=(",", ":")).encode(),
                           sealed.SECTION_TEXT: b"different text"})
    key = aead.gen_key()
    nonce, ct = aead.encrypt(key, broken, aad=b"DOC-0000")
    forged = {"doc_id": "DOC-0000", "nonce": nonce.hex(), "ciphertext": ct.hex()}
    with pytest.raises(sealed.SealedError, match="does not match the hash"):
        ca.open_payload(forged, key)
