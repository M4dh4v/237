# SĀKṢYA — Evidence-grade attribution for leaked documents

> Project description for SIH problem statement **SIH26237** (WESEE / Indian Navy).
> Written to be pasted into a submission, report, or deck. The two places where
> the problem statement's literal wording and the implementation differ are
> marked **[disclosed]** rather than overclaimed — a tool that knows the limit
> of its own claim is the one a defence evaluator believes (see `CLAUDE.md` and
> the `sakshya-honesty` skill).

---

## Description

**One line.** SĀKṢYA is an offline, post-quantum forensic-attribution instrument
that gives every recipient of a broadcast-distributed document a copy that reads
as an ordinary copy but quietly carries a hidden fingerprint grown from a
tamper-evident ledger entry written at the moment of decryption — so a leaked
document traces to exactly one recipient's key, device and session, with proof
that no single administrator can rewrite.

**The problem.** Under broadcast-encrypt / individually-decrypt distribution, a
sender encrypts one file and many recipients each decrypt it with their own
credentials. When that file leaks, every recipient who *could* decrypt becomes
an equally plausible suspect: the plaintext is the same for all of them and
carries no trace of which decryption produced the leaked copy. Existing
safeguards fail for structural reasons. Server-side access logs can be edited by
a privileged administrator, so they are not evidence. A watermark applied before
distribution is identical on every copy, which reproduces the very attribution
problem it was meant to solve.

**The core idea — bind the mark to the open event.** SĀKṢYA inverts the usual
order of operations: *the record is written first, the key is released second.*
When a recipient opens a document, their own post-quantum signing key signs the
decryption request ("I am opening document X now"). That signed request is
committed as a leaf in a shared, append-only Merkle ledger and co-signed by
independent witnesses; **only after that commit succeeds** is the content key
released. The mark is then derived from the committed leaf itself —
`seed = HKDF-SHA256(leaf_hash)` — and embedded into the copy the recipient
receives. Because the mark and the ledger entry are the same object, neither can
exist without the other.

**From a leak to a name.** A leaked copy — a pasted paragraph, a screenshot, or a
photographed page — is fed to the trace tool. The pipeline identifies the source
document (TF-IDF), aligns it to the master (LCS), recovers the hidden bits from
the linguistic mark, and searches candidate seeds. The pointer embedded in the
mark is self-validating: the seed from leaf *N* must recover a pointer that names
*N*, so a forged or spliced mark fails to validate rather than accusing the wrong
person. The recovered entry yields the recipient's own signature, the Merkle
inclusion proof, the witness co-signatures, and any covering anchor, which
together form an independently verifiable evidence record.

**Cryptography.** Key exchange uses **ML-KEM-768 (FIPS 203)**; signatures use
**ML-DSA-65 (FIPS 204)**; long-term ledger anchors use **SLH-DSA (FIPS 205)** —
all via liboqs against NIST known-answer vectors, with no classical primitives on
the evidence path.

**The audit layer.** Immutability is provided by a **permissioned distributed
ledger**: an RFC 6962 append-only Merkle transparency log whose every tree head
is co-signed by multiple independent witness processes (quorum 2 of 3 by
default). Witnesses enforce three refusals in code — equivocation (two different
roots at the same size), rollback (a head behind their own high-water mark), and
unproven extension — so a compromised administrator cannot rewrite or erase
history without defeating every witness at once. There is no token, no mining,
and no public network.

---

## How the solution addresses each PS requirement

| PS requirement | How it is met |
|---|---|
| Unique invisible watermark at the moment of decryption | Mark derived from the committed ledger leaf and embedded client-side at open |
| Specific to recipient **and** session | Seed = HKDF(leaf hash); two opens of the same document yield two different marks |
| Visually identical, forensically distinct | **[disclosed]** copies are reader-indistinguishable and semantically identical, but not byte-identical — the mark rides in word choice (see limits) |
| Decryption bound to recipient identity | The decryption record *is* the recipient's ML-DSA-65 signature over their request |
| Signed with the recipient's own private key | Signed client-side; the authority never holds it; non-repudiable |
| NIST PQC for key exchange and signatures | ML-KEM-768, ML-DSA-65, SLH-DSA — verified against KAT vectors |
| Immutable audit via blockchain/DLT | RFC 6962 Merkle transparency log with multi-witness co-signing (permissioned DLT — not a public chain) |
| No single admin can alter records | Witness equivocation/rollback/extension refusals; the log's own key cannot rewrite co-signed history |
| Extract watermark from a leak | Text-domain extractor with OCR front-end for images/photos, aligned to the master |
| Look the watermark up in the ledger | Self-validating seed search; only a leaf whose own seed returns its own index matches |
| Return a cryptographically verifiable record | Evidence bundle + a standalone verifier that imports nothing from the main codebase |
| Fully offline / air-gapped | Single origin `127.0.0.1`; nothing an upload contains leaves the machine |
| No cloud KMS / no public chain | All keys and operations local; no external dependency |

---

## Honest limits — stated, not hidden

1. **Copies are not byte-identical.** The mark is linguistic (synonym
   substitution), so word choices differ between recipients. Each copy *reads as
   an ordinary copy*; we never claim pixel-identity, and we show the word-level
   difference as proof of the mechanism.
2. **Attribution proves a key, device and session — not a person.** Every result
   and the certificate carry this fixed caveat.
3. **Collusion is ranked, not named at real document lengths.** At the demo's
   document length the collusion code yields roughly 116 mark positions where the
   formal Tardos bound needs ~655, so suspected colluders are returned as a
   ranked shortlist with scores. *(Numbers measured from the current code and
   config; an earlier draft of the design plan cited "~185 vs ~1201", which
   corresponds to a longer document and a stricter error bound than the
   deployment actually runs.)*
4. **The mark is text-domain.** Text-bearing documents trace best; this is
   disclosed where uploads are accepted.
5. **Key management in this build is demo-grade and labelled as such.** The
   authority's KEM secret and the log's signing key are held locally in ordinary
   files for the demo; a production build would place them in an HSM/TPM. This is
   disclosed, not hidden.

---

## Deployment

The entire system — cryptography, identity and certificate authority, watermark
generation, ledger, witnesses and forensic verification — runs on a single
air-gapped host with no internet, no cloud KMS and no public blockchain. The
backend API binds `127.0.0.1:8443`; the console is served locally; all
dependencies, fonts and assets are vendored.

---

## End-to-end workflow

1. The sender seals the document and distributes it to authorised recipients.
2. An authorised recipient requests to open it with their credentials.
3. The request is signed **with the recipient's own post-quantum signing key**.
4. That signed record is committed to the ledger and co-signed to witness quorum.
5. **Only then** is the content key released.
6. The system embeds a hidden mark derived from that exact committed entry, and
   the recipient receives their uniquely fingerprinted copy.
7. If the copy leaks, the mark is extracted from the leaked artefact.
8. The mark is matched against the ledger via a self-validating seed search.
9. The associated signatures, inclusion proof and witness co-signatures are
   checked — by the standalone, independent verifier.
10. The system produces a verifiable record identifying the recipient and the
    decryption event.

---

## Short form (portal / abstract field)

> SĀKṢYA is an offline, post-quantum instrument for attributing leaked
> classified documents. A sender seals one document and distributes it to many
> authorised officers. Opening a copy is a single atomic event: the recipient's
> own ML-DSA-65 signature over "I am opening document X now" is written into a
> shared, tamper-evident Merkle ledger co-signed by independent witnesses, and
> only after that record commits is the key released and the copy fingerprinted
> with a hidden mark grown from that exact ledger entry. Because the mark and the
> ledger entry are the same object, a leaked copy — even a screenshot, a paste,
> or an OCR-degraded photo — traces to the exact key, device and session, with
> proof anyone can verify without trusting the administrator. It runs air-gapped
> on `127.0.0.1`: no cloud, no public chain. Its limits are disclosed, not
> hidden: the mark rides in the text layer, collusion is ranked rather than named
> at real document lengths, and attribution is strong evidence about a key, not a
> confession by a person.
