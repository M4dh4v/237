# Abstract

**Project title:** SĀKṢYA — Post-quantum forensic attribution for leaked documents

**Problem statement:** SIH26237 (WESEE / Indian Navy) · Category: Software

**Keywords:** post-quantum cryptography · ML-KEM-768 · ML-DSA-65 · SLH-DSA ·
linguistic watermarking · transparency log · RFC 6962 · tamper-evident ledger ·
document attribution · air-gapped systems

---

## Abstract

When a sensitive document is broadcast-encrypted once and decrypted
independently by many recipients, a subsequent leak cannot be attributed: the
decrypted plaintext is identical for every recipient and carries no record of
which decryption produced the leaked copy, so every holder of a valid credential
is an equally plausible suspect. The usual safeguards do not close this gap.
Server-side access logs are mutable by a privileged administrator and are
therefore unverifiable as evidence, while a watermark applied before
distribution is the same on every copy and merely relocates the problem it was
meant to solve.

SĀKṢYA is an offline, post-quantum forensic-attribution instrument that binds
each decrypted copy to the act of decryption itself. The system inverts the
conventional order of operations — the record is written first and the key is
released second. When a recipient opens a document, their own post-quantum
signing key signs the decryption request; that signed record is committed as a
leaf in a shared, append-only Merkle ledger and co-signed by independent
witnesses; only once that commitment succeeds is the content key released. The
hidden forensic mark is then derived from the committed leaf itself
(`seed = HKDF-SHA256(leaf_hash)`) and embedded into the copy the recipient
receives. Because the mark and the ledger entry are the same object, neither can
exist without the other, and the recipient cannot later deny the decryption
because the record is signed with their own private key.

Cryptographic operations use NIST-standardised post-quantum algorithms
throughout: ML-KEM-768 (FIPS 203) for key exchange, ML-DSA-65 (FIPS 204) for
signatures, and SLH-DSA (FIPS 205) for long-term ledger anchors, validated
against known-answer vectors. Immutability is provided by an RFC 6962 Merkle
transparency log whose every tree head is co-signed by multiple independent
witnesses; the witnesses enforce refusals against equivocation, rollback, and
unproven extension in code, so no single administrator or compromised account
can retroactively alter or erase the audit record. Given a leaked copy — pasted
text, a screenshot, or a photographed page — the trace tool identifies the
source document, recovers the embedded mark, and performs a self-validating seed
search that maps it to the exact ledger entry. The result is a cryptographically
verifiable record identifying the recipient, with verification performed by a
standalone verifier that imports none of the main system's code and therefore
does not rely on trusting the administrator.

The complete system runs within an air-gapped environment on a single host, with
no cloud KMS and no public blockchain dependency. The design's limits are stated
rather than hidden: the mark is linguistic and therefore best recovered from
text-bearing documents; collusion is ranked rather than named at realistic
document lengths; and attribution is strong evidence about a key, device and
session rather than proof of the human who held it.

---

## Condensed abstract (≈120 words)

SĀKṢYA attributes leaked documents in a broadcast-encrypt, individually-decrypt
distribution. Its central mechanism is log-before-open: a recipient's own
post-quantum signature over the decryption request is committed to a
tamper-evident Merkle ledger and co-signed by independent witnesses, and only
then is the key released. The copy is fingerprinted with a mark derived from that
committed entry (`seed = HKDF(leaf_hash)`), so the copy and the ledger record are
one object. ML-KEM-768, ML-DSA-65 and SLH-DSA provide post-quantum key exchange,
signatures and anchors; witnesses refuse equivocation, rollback and unproven
extension, so no single administrator can rewrite the record. A leaked copy is
traced to the exact recipient via a self-validating seed search and verified by a
standalone, independent verifier. The system runs fully air-gapped, without cloud
KMS or public blockchain.
