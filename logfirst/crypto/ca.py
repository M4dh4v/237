"""The offline root CA, and document distribution.

The CA's signing key never touches the network. It issues recipient
certificates -- a signed binding of an identity to an ML-KEM and an ML-DSA
public key -- and then goes away. The authority service holds only the CA's
*public* key, which is enough to verify a certificate and not enough to mint
one. That separation is what stops a compromised authority from inventing a
recipient and then attributing a leak to them.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from ..models import Certificate, canon
from . import aead, pqc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CA:
    def __init__(self, sig_pub: bytes, sig_sec: bytes):
        self.sig_pub = sig_pub
        self.sig_sec = sig_sec

    @classmethod
    def create(cls) -> "CA":
        pub, sec = pqc.sig_keypair(pqc.SIG)
        return cls(pub, sec)

    def issue(self, recipient_id: str, kem_pub: bytes, sig_pub: bytes,
              role: str = "recipient") -> Certificate:
        cert = Certificate(
            recipient_id=recipient_id,
            kem_alg=pqc.KEM,
            sig_alg=pqc.SIG,
            kem_pub=kem_pub.hex(),
            sig_pub=sig_pub.hex(),
            serial=secrets.token_hex(8),
            issued_at=now_iso(),
            role=role,
        )
        cert.ca_sig = pqc.sign(self.sig_sec, cert.tbs(), pqc.SIG).hex()
        return cert

    def verify(self, cert: Certificate) -> bool:
        if not cert.ca_sig:
            return False
        return pqc.verify(self.sig_pub, cert.tbs(), bytes.fromhex(cert.ca_sig))


def enroll_recipient(ca: CA, recipient_id: str, role: str = "recipient"):
    """Generate a recipient's two keypairs and issue their certificate.

    Returns ``(cert, secrets)``. ``secrets`` is the private half and in a real
    deployment never leaves the recipient's device -- here it is returned so the
    synthetic-data generator and the demo client can act as that recipient.
    """
    kem_pub, kem_sec = pqc.kem_keypair(pqc.KEM)
    sig_pub, sig_sec = pqc.sig_keypair(pqc.SIG)
    cert = ca.issue(recipient_id, kem_pub, sig_pub, role=role)
    return cert, {"kem_sec": kem_sec.hex(), "sig_sec": sig_sec.hex()}


def cert_fingerprint(cert: Certificate) -> str:
    return hashlib.sha256(canon({"recipient_id": cert.recipient_id,
                                 "kem_pub": cert.kem_pub,
                                 "sig_pub": cert.sig_pub})).hexdigest()[:16]


# --------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------

def _doc_aad(doc_id: str) -> bytes:
    return doc_id.encode("utf-8")


# There used to be an ``encrypt_document`` here that sealed raw text. It is gone
# rather than kept beside the framed path, because a second way to seal a
# document -- producing packages the decryptor cannot read -- is not a spare
# primitive, it is a trap. Everything that seals goes through
# :func:`encrypt_framed_payload` and everything that opens goes through
# :func:`open_payload`, so the two cannot disagree about what a sealed document
# is.
#
# The property its docstring recorded still holds, and is worth keeping said: no
# recipient key is used at seal time and no recipient holds a key share. The
# package is identical for every intended reader; who may open it is decided
# later, per request, by the authority -- and recorded when it does.


def verify_document_hash(package: dict, plaintext) -> bool:
    raw = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
    return hashlib.sha256(raw).hexdigest() == package["doc_hash"]


def encrypt_framed_payload(text: str, pdf: bytes, doc_id: str,
                           classification: str, server_kem_pub: bytes,
                           *, extra_manifest: dict | None = None) -> dict:
    """Seal a document as a frame carrying its text *and* its PDF.

    The frame is what makes the distributed artefact a real object rather than a
    convention: the PDF inside it is the one that was sealed, not one re-rendered
    later from the same text, so a recipient can check that what they hold is
    what was sent.

    Both halves are needed and neither is redundant. The *text* is what the
    linguistic watermark is a transformation of, and the mark has to be embedded
    by the client on the plaintext it decrypted -- so the text must survive into
    the envelope. The *PDF* is what a person actually opens, and it must be the
    sealed one for the same reason a signed document is signed rather than
    re-typeset.

    ``doc_hash`` is the hash of the **text**, exactly as it is for an unframed
    document. It is not redefined to cover the frame: it is a stored field with a
    meaning, and changing that meaning would silently change what
    :func:`verify_document_hash` checks and what the demo displays as a content
    hash. The PDF gets its own ``pdf_hash``.

    ``extra_manifest`` is merged into the authenticated manifest. It exists so
    that facts about the rendering -- the font, the page count -- can be recorded
    by the caller that knows them, without this module having to know anything
    about how a PDF is made.
    """
    from .. import sealed
    from .onetime import seal_content_key

    text_bytes = text.encode("utf-8")
    pdf_bytes = pdf if isinstance(pdf, bytes) else bytes(pdf)

    manifest = {
        "doc_id": doc_id,
        "classification": classification,
        "doc_hash": hashlib.sha256(text_bytes).hexdigest(),
        "pdf_hash": hashlib.sha256(pdf_bytes).hexdigest(),
        "frame": sealed.FRAME_NAME,
    }
    manifest.update(extra_manifest or {})

    manifest_bytes = canon(manifest)
    payload = sealed.frame({
        sealed.SECTION_MANIFEST: manifest_bytes,
        sealed.SECTION_TEXT: text_bytes,
        sealed.SECTION_PDF: pdf_bytes,
    })

    key = aead.gen_key()
    nonce, ct = aead.encrypt(key, payload, aad=_doc_aad(doc_id))
    return {
        "doc_id": doc_id,
        "classification": classification,
        "doc_hash": manifest["doc_hash"],
        "pdf_hash": manifest["pdf_hash"],
        "frame": sealed.FRAME_NAME,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sections": sealed.section_table(manifest_bytes, text_bytes, pdf_bytes),
        "nonce": nonce.hex(),
        "ciphertext": ct.hex(),
        "key_envelope": seal_content_key(server_kem_pub, key),
        "cipher": "AES-256-GCM",
        "kem_alg": pqc.KEM,
        "created": manifest.get("created"),
        "font": manifest.get("font"),
        "pages": manifest.get("pages"),
    }


def decrypt_bytes(package: dict, content_key: bytes) -> bytes:
    """The AEAD open, returning the raw sealed bytes.

    Split out from :func:`decrypt_document` because the payload is no longer
    necessarily text: it is a frame that contains text. Decoding is the caller's
    business, and a function that decodes cannot return a PDF.
    """
    return aead.decrypt(content_key, bytes.fromhex(package["nonce"]),
                        bytes.fromhex(package["ciphertext"]),
                        aad=_doc_aad(package["doc_id"]))


def open_payload(package: dict, content_key: bytes) -> dict:
    """Decrypt and unpack a sealed document into its parts.

    Returns ``{manifest, text, pdf, sections}``. The manifest is the
    authenticated description that travelled *inside* the encryption, and it is
    the one to believe: the copy in a container's header is unauthenticated and
    anyone holding the file can edit it (:func:`logfirst.sealed.compare` is how
    the two are checked against each other).

    Both hashes are verified here, so a payload whose parts do not match the
    description they were sealed with is an error rather than a document that
    quietly differs from the one that was distributed.
    """
    import json

    from .. import sealed

    sections = sealed.unframe(decrypt_bytes(package, content_key))
    try:
        manifest = json.loads(sections[sealed.SECTION_MANIFEST].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise sealed.SealedError(f"payload manifest is unreadable: {e}") from e

    text_bytes = sections[sealed.SECTION_TEXT]
    pdf_bytes = sections.get(sealed.SECTION_PDF, b"")

    text_hash = hashlib.sha256(text_bytes).hexdigest()
    if manifest.get("doc_hash") and manifest["doc_hash"] != text_hash:
        raise sealed.SealedError(
            "the sealed text does not match the hash recorded for it")
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if manifest.get("pdf_hash") and manifest["pdf_hash"] != pdf_hash:
        raise sealed.SealedError(
            "the sealed PDF does not match the hash recorded for it")

    return {
        "manifest": manifest,
        "text": text_bytes.decode("utf-8"),
        "pdf": pdf_bytes,
        "sections": sections,
    }


def decrypt_document(package: dict, content_key: bytes) -> str:
    """Decrypt with a content key recovered from the authority.

    Returns text. These are documents, and every consumer downstream -- the
    watermark embedder, the aligner, the corpus index -- works on text, so
    decoding here is what keeps a stray ``b'...'`` from reaching a regex that
    would silently match nothing.

    A sealed document is a frame holding the text and the PDF that was
    distributed; this returns the text out of it, so a caller that only wants
    the prose does not have to know the payload has a shape at all. Use
    :func:`open_payload` when the PDF is wanted too.
    """
    return open_payload(package, content_key)["text"]
