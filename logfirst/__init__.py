"""logfirst -- log-first, post-quantum, recipient-attributable documents.

The one-line pitch: *a document that cannot be decrypted without first signing
its own confession.*

Every open is gated by a central authority that will not derive or release a key
until the recipient's own post-quantum signature has been committed to a
tamper-evident Merkle ledger, co-signed by independent witness processes. The
forensic mark embedded in that copy is derived from that exact ledger entry, so
a leaked screenshot and an immutable cryptographic record are two views of the
same event.

Structure:

``crypto/``     PQ primitives, AEAD, KDF, the one-time key lifecycle, mTLS.
``ledger/``     RFC 6962 Merkle math, the append-only log, the witness quorum.
``witness/``    The witness node: a separate process with its own key.
``authority/``  The network-facing key authority. Holds the only copy of K.
``client/``     A recipient node. Holds ciphertext and nothing else.
``watermark/``  Linguistic mark, Tardos collusion code, Reed-Solomon, OCR.
``forensics/``  The leak-check pipeline: identify, align, decode, verify.
``data/``       Synthetic corpus and identity generation.
``verifier/``   Standalone verification, stdlib + liboqs only.
"""

__version__ = "0.1.0"
