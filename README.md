# logfirst

**A document that cannot be decrypted without first signing its own confession.**

Every open is gated by an authority that refuses to release a key until the
recipient's own post-quantum signature has been written to a tamper-evident
ledger — and the forensic watermark in the copy they receive is derived from that
exact ledger entry. So the copy on a leaker's disk and the entry naming them are
the same object, and neither can be produced without the other.

```
        sender                     AUTHORITY                      recipient
          │                     (network-facing)                     │
          │  seal: K wrapped under the authority's ML-KEM key         │
          ├────────────────────────►│                                 │
          │                         │  ciphertext only ──────────────►│
          │                         │                    (no key material)
          │                         │                                 │
          │                         │◄── signed open request ─────────┤
          │                         │    {docID, recipientID, nonce,  │
          │                         │     timestamp, deviceFP,        │
          │                         │     ephemeral_kem_pub}          │
          │                         │    ML-DSA-65, over mTLS         │
          │                         │                                 │
          │                    ┌────┴─────┐                           │
          │                    │ 1. append request to Merkle ledger  │
          │                    │ 2. STH co-signed by ≥2 witnesses    │
          │                    │    — a network round trip each      │
          │                    │ 3. only now: unwrap K, re-wrap to   │
          │                    │    the client's ephemeral KEM key   │
          │                    └────┬─────┘                           │
          │                         ├─────────────────────────────────►│
          │                         │  {one_time_key, watermark_seed,  │
          │                         │   inclusion_proof, sth,          │
          │                         │   witness_sigs}                  │
          │                         │                                  │
          │                         │   client decrypts, embeds the    │
          │                         │   mark, discards K               │
```

The ordering is the whole design. If step 3 can be reached without steps 1 and 2
having committed, the system is an ordinary DRM server with extra cryptography
bolted on.

---

## Quick start

```bash
make bootstrap   # venv, dependencies, and a real check of liboqs + tesseract
make test        # ~3.5 minutes: 522 tests, real processes, real sockets
make demo        # the eight-step scripted walkthrough
make tamper      # tamper with a committed entry; watch every check catch it
make demo-serve  # API on :8443 and the console on http://127.0.0.1:5173
```

Then, the independent half:

```bash
make generate    # write a synthetic deployment and an evidence bundle
make verify      # re-check it with a verifier that does not import logfirst
```

`make generate` ends by running the leak-check pipeline over every artefact it
just produced, and exits non-zero if any is not recovered. That report is the
point of the generator: data that merely *looks* like a leak corpus is easy, and
`tests/test_generate.py` re-derives every number the manifest claims from the
files on disk rather than trusting the summary — a generator is the one
component free to describe a run that never happened.

`make help` lists everything. Every target is a thin wrapper over a documented
command, so you can always read and run the command itself.

---

## The two files

Distributing produces one file; opening produces another. They are different in
kind, and the difference is the system.

### `DOC-0000.lfdoc` — what gets distributed

An opaque container: `LFDOC\0\1`, a JSON header, then the ciphertext as raw
bytes. It is **not a PDF**, and this is checkable rather than asserted:

```bash
file DOC-0000.lfdoc            # data
grep -c '%PDF' DOC-0000.lfdoc  # 0
pdftotext DOC-0000.lfdoc -     # exits 1
python -m logfirst.sealed describe DOC-0000.lfdoc   # the header, no plaintext
```

Inside is a length-prefixed frame with three sections — the manifest, the
canonical text, and the PDF that was sealed — all encrypted under a content key
`K`. `K` itself is wrapped to the authority's ML-KEM-768 **public** key and that
wrapped form travels in the header, in the clear. That is deliberate: it makes
the file a complete description of itself rather than something that only means
anything next to the server's database. It is a locked box and the lock, and the
key is on the server.

Two properties of the header have to be said out loud, because both look like
bugs and neither is one:

* **The header is not authenticated.** AES-GCM's additional data here is only
  the `doc_id`, so `classification`, `pages`, `pdf_hash` and `created` can be
  edited by anyone holding the file. Tampering with `doc_id`, `nonce`,
  `ciphertext` or `key_envelope` *does* break decryption — but the descriptive
  fields do not. So the header is a **label**, and `logfirst.sealed.compare`
  exists to check it against the manifest, which travelled *inside* the
  encryption. A reader who has not made that comparison has not learned anything
  the file's author could not have written (`tests/test_sealed.py` drives both
  the tamper and the honest case).
* **The section table leaks sizes.** It reports the byte length and sha256 of
  the text and the PDF. That is the same class of leak as publishing a document
  hash, and it is stated rather than hidden.

The console's **"Open a .lfdoc"** tab reads that header in the browser, with no
key and no request to the server, and then does the two things that are actually
available to it. It hashes the file it was handed and the authority's container
for the `doc_id` the header names, and refuses to enable the open button unless
they match — which matters precisely because the header is unauthenticated: the
authority opens *its* document, chosen by a `doc_id` out of a label anyone could
have written, so without that comparison a doctored label yields a PDF from a
document the reader was never sent. After a real open it compares the header
with the manifest that came out of the encryption, which is the first point at
which the label is checkable rather than merely readable. The page never
previews the container; the inline preview is of the *opened, marked* copy, and
it is labelled with the entry that produced it.

### `DOC-0000-<recipient>-marked.pdf` — what the recipient keeps

A real PDF, which opens in any viewer, and whose *text* is the marked text. That
last part is the whole point of rendering rather than rasterising: `pdftotext`
on it, or OCR of a printout, still recovers the mark.

It can only exist after an open, because the mark is derived from the leaf hash
of that open's ledger entry, and at distribution no such entry exists. So the
envelope ships the **canonical** rendering, and the marked copy is rendered from
the marked text on the recipient's side. Two opens of one document give the same
`distribution_pdf` and two *different* marked copies.

When a document is too short to carry a mark, the API returns `pdf_marked:
false` and the UI does not offer a "marked PDF" — the file would be identical to
the plaintext and labelling it as evidence would be a quiet lie.

### The glyph guard

`fpdf2` does not raise when a font cannot draw a character: it logs a warning
and renders the text **with those characters missing**. For a marked copy that
is not cosmetic — the delivered text would no longer be the text the watermark
was embedded in, so the mark would fail to decode while the document looked
perfectly fine. `logfirst.pdfdoc` checks every codepoint against the font's cmap
*before* rendering and refuses, naming the codepoints, unless the caller opts in
with `allow_replacements=True` and is told how many substitutions were made.

### What is simulated here

The "sender" rendering the distribution PDF is the demo server, not a separate
authoring client: the seal path renders and encrypts in one place so the demo can
be driven from a browser. A real deployment authors and renders the document
before it ever reaches the authority.

### Installing liboqs

The one dependency that is not a `pip install`, and the one whose absence fails
in the most misleading way possible: `liboqs-python` imports fine without the
native `liboqs.so`, and the error surfaces much later as **a signature that does
not verify** — that is, as the verifier reporting a tampered ledger. This is the
worst false positive the system can produce, so it is checked by *using* each
algorithm rather than by importing the module:

```bash
git clone https://github.com/open-quantum-safe/liboqs
cmake -B liboqs/build -DLIBOQS_BUILD_ONLY_LIB=ON liboqs
cmake --build liboqs/build -j
export LD_LIBRARY_PATH=$PWD/liboqs/build/lib:$LD_LIBRARY_PATH   # or set OQS_LIB for make
python scripts/check_env.py       # verifies ML-KEM-768, ML-DSA-65 and SLH-DSA by using them
```

`make check-liboqs` runs the same check. It reports `[ FAIL ]` rather than a
traceback, and says what is actually wrong.

---

## What is real, and what is simulated

The distinction matters more here than in most projects, because most of the
system's value is in claims about what *cannot* be done. Anything that makes a
guarantee weaker is listed here rather than left to be discovered.

### Real — no simulation, no stand-in

| | |
|---|---|
| **Post-quantum cryptography** | ML-KEM-768 (FIPS 203), ML-DSA-65 (FIPS 204), SLH-DSA-SHA2-128s (FIPS 205) via liboqs. Checked against liboqs's own NIST-format known-answer vectors (`tests/test_crypto_kat.py`). |
| **The ledger** | RFC 6962 Merkle tree: real inclusion proofs, real consistency proofs, real STHs. The arithmetic is unit-tested against the RFC's vectors (`tests/test_merkle.py`). |
| **Witness co-signatures** | Real witness processes, on their own ports, answering over HTTP. The authority reaches them with `httpx` inside the append transaction. |
| **The refusal rules** | The witnesses really decline: equivocation, rollback, unproven extension. `make tamper` provokes all three and prints the refusal text. |
| **The standalone verifier** | A separate program that re-derives every check from the bundle's public outputs. `tests/test_verifier_independence.py` asserts it imports nothing from `logfirst` — statically, by scanning its imports, and dynamically, by running it in a subprocess where importing the package raises. |
| **OCR** | The system `tesseract` 5.5.3 binary. Real rendered images, degraded, OCR'd back, aligned, decoded. |
| **The watermark** | Synonym substitution driven by a keystream derived from the ledger entry's hash, with Tardos collusion codes and Reed–Solomon error correction. |
| **Ledger entries** | Every entry in every demo and test is the output of the real code — real signatures, real witness round trips. Nothing is hand-written. |

### Simulated — and it weakens something specific

| Simulation | What it costs |
|---|---|
| **Witnesses are separate processes on one machine**, not separate hosts. | They share a kernel, a filesystem, and an administrator. A real deployment puts them under different operators; the entire collusion resistance of the ledger rests on that separation, and one laptop does not provide it. |
| **The CA private key and the authority's KEM private key sit in `deployment.json` in plaintext.** | A real deployment keeps the CA offline and the KEM key in an HSM. As built, anyone who can read the deployment directory can mint a recipient certificate or unwrap every document key. |
| **The log's private key is in the same SQLite file as the ledger.** | A real deployment keeps it in an HSM the operator cannot read. This is why `make tamper` includes the attack that re-signs the rebuilt head: the demo grants the attacker that key, because in this build they have it. What they still cannot do is reach an externalized root — which is the point. |
| **The device fingerprint is a random salt in the deployment file**, not a TPM attestation. | `device_fp` is minted at enrolment, asserted by the client, and signed into the request — so the ledger proves a key claimed that value, and nothing establishes it is true. No hardware is read and the authority never compares the enrolled value with the asserted one. Treat it as corroboration, never as proof of which machine. |
| **Documents are template prose** from `data/corpus.py`, not natural language. | The measured marker densities are *achievable*, not *typical*. A real corpus with fewer synonym pairs would carry fewer positions, and the capacity floor (below) would refuse more documents. |
| **OCR degradation is modelled** by rasterise/recompress/rescale, not by photographing a screen. | A photo adds perspective, moiré, and uneven lighting that resampling does not produce. The measured error rates below are a floor, not an estimate of the field. |
| **Synthetic corpus and sessions** are generated programmatically. | Scale is demonstrated, not earned. |

---

## Honesty: what an attribution does and does not mean

This is the part most likely to be misused, so it is enforced in the code rather
than described in a document nobody reads. The API returns
`attribution_caveat` on every open, and the leak-check report carries it on every
result.

**An attribution proves which key decrypted a document, at which time, and whose
signature authorised it.** It does not prove that a specific human leaked it.

Concretely:

- A key on a shared workstation, a session left unlocked, a device stolen, a
  signature made under duress, or a recipient who was impersonated all produce a
  ledger entry that is cryptographically perfect and points at the wrong person.
  The ledger is evidence about *keys*, and the inference from key to person is an
  argument someone has to make, not a fact the system establishes.
- `source_ip` is recorded on every entry and is **unauthenticated and trivially
  spoofable**. It is investigation metadata, never evidence.
- `device_fp` is on every entry and is stronger than `source_ip` and still not
  evidence of a machine. It sits inside the signed request, so the ledger proves
  the recipient's key committed to that value and they cannot deny it — but the
  recipient chooses it, no hardware is read, and the authority never compares it
  with the value enrolment recorded. The register shows both side by side for
  exactly this reason: a mismatch is a thing to look at, not a determination.
- When watermark recovery fails or is low-confidence, the system falls back to
  the ledger alone and **says so**, labelling it as weaker corroborating
  evidence. It does not upgrade a failure to an accusation.
- The system **never returns a single named suspect without a confidence score**.
  Document-match confidence and watermark-recovery confidence are reported
  separately, because they fail independently: misidentifying which document a
  fragment came from is a different error from failing to read its mark.

---

## What the measurements actually are

Every number below is produced by code in the tree and asserted by a test, so it
cannot drift silently away from the claim it supports.

### Watermark capacity

Slots are synonym-group positions in the document, at roughly one per 8–12 running
words. The pointer block costs a fixed 120 slots (40 bits × 3-fold repetition);
whatever remains can carry Tardos positions.

| Target length | Actual words | Slots | Pointer | Tardos | Rep. | Result |
|---|---|---|---|---|---|---|
| 600 | 692 | 88 | — | — | — | **refused**: 88 < 120 |
| 900 | 923 | 117 | — | — | — | **refused**: 117 < 120 |
| 1200 | 1275 | 160 | 120 | 0 | 4× | marked pointer-only |
| 1500 | 1509 | 190 | 120 | 70 | 1× | ranking-only |
| 1800 | 1854 | 236 | 120 | 116 | 1× | ranking-only |
| 2400 | 2424 | 305 | 120 | 185 | 1× | ranking-only |

**A document below 120 slots is refused rather than weakly marked.** A mark that
cannot survive is worse than no mark, because it produces confident-looking
evidence that is not there.

> **The formal Tardos bound is never met at these lengths.** The provable
> false-accusation guarantee holds only above a code length of
> `2π²c²ln(n/ε)` — **1201 positions** for 4 users at `c=2, ε=10⁻⁶`. The longest
> document above yields 185. So the code reports `guarantee: "ranking-only"` in
> every realistic case: suspects may be *ranked* and their scores reported, but
> no single name may be presented as an accusation with a stated false-positive
> rate. This is surfaced through the API, not buried here.

### The watermark through a real OCR pass

Rendered, degraded, OCR'd with the system `tesseract` 5.5.3, aligned by LCS, and
decoded. Seed 7, three documents, four degradations each:

| Degradation | n | mean channel BER | max channel BER | mean payload BER | max payload BER |
|---|---|---|---|---|---|
| clean | 3 | 0.0031 | 0.0047 | 0.0000 | 0.0000 |
| jpeg50 | 3 | 0.0015 | 0.0045 | 0.0000 | 0.0000 |
| resize60 | 3 | 0.0015 | 0.0045 | 0.0000 | 0.0000 |
| combo | 3 | 0.0015 | 0.0045 | 0.0000 | 0.0000 |
| **overall** | **12** | **0.0019** | **0.0047** | **0.0000** | **0.0000** |

Pointer recovered: **12/12**.

- *Channel BER* is the fraction of carrier slots whose OCR'd word differs from
  the canonical one. This is the number the repetition budget rests on, and it is
  measured **before** any coding — so it is not flattered by the error correction
  it justifies.
- *Payload BER* is the fraction of payload bits wrong after per-position majority
  voting and RS decoding.
- The budget in `payload.py` uses **p = 0.008**, well above the measured 0.0047,
  because the cost of under-provisioning is a document that looks marked and is
  not. The test's ceiling is 0.02.

### Tardos: ranking is not accusation

Measured on the synthetic corpus (4 users, ~1850-word documents, ~116 Tardos
positions, scores masked to the positions the extractor actually *read*):

| Population | n | top score / Z |
|---|---|---|
| unmarked copy of the plaintext | 7 | 0.02 – 0.24 |
| fragment too short to reach the region | 8 | no positions read |
| one recipient's marked copy, whole | 4 | **1.28 – 1.70** |
| one recipient's marked copy, 35% fragment | 2 | 0.84 – 0.87 |
| splice of two colluders | 40 | 0.65 – 1.14 |

Two things follow, and both are deliberate:

1. **A real colluder's score sits at a fraction of the formal threshold Z**,
   which is why `accuse()` names nobody at these lengths. Naming a person is a
   strong claim and the evidence at this scale does not support it. The report
   ranks and gives scores; it does not accuse.
2. **The classification is three-way, not boolean** — `no-mark`, `single-user`,
   `collusion` — because the two ways of *not* being a collusion are different
   things to say. Those three map to three API statuses (`no-watermark`,
   `single-mark`, `collusion-suspected`) so that a consumer reading only the
   machine-readable field cannot be told the opposite of what the note beside it
   says. The cuts (`MARK_PRESENT = 0.40`, `USER_ELEVATED = 0.35`) sit in the
   measured gaps, and `tests/test_collusion_indicator.py` **re-measures both
   populations** rather than trusting them, so a change to the corpus or the code
   length cannot silently invalidate the separation.

A splice can resolve almost entirely in one colluder's favour: the arcsine bias
puts most positions near p=0 or p=1, where two users usually share a bit, so a
few dozen positions decide it. Those lopsided cases are reported as
`single-user` rather than `collusion`, deliberately — from the score vector alone
they are not separable from a fragment of one copy. **The error is biased toward
understating**: calling a mixture a single mark understates what is known, while
calling a single mark a collusion states something false about people. In every
splice measured, the top-ranked user was a real colluder.

### Document identification

TF-IDF cosine over (1,2) word n-grams, floor `MIN_IDENTIFY_SCORE = 0.25`:

| | score |
|---|---|
| in-corpus matches | 0.307 / 0.412 / 0.636 |
| best out-of-corpus match | 0.063 – 0.201 |

---

## The five attacks the system exists to stop

`make tamper` runs all of these against a live deployment and prints
`caught`/`NOT CAUGHT` for each. The script exits non-zero if any goes undetected,
and `tests/test_tamper_demo.py` asserts each refusal *with its own reason* — a
change that made one rule fire in place of another would still show a caught
attack and a green summary, so matching the refusal text is what keeps them
distinct.

| # | Attack | Caught by |
|---|---|---|
| 1 | Rewrite a committed entry in the ledger's own database | The entry no longer folds to the root the witnesses signed. |
| 2 | Rewrite it, rebuild the tree, and **re-sign the head with the log's own key** | The rebuilt head is not a consistent extension of the root already externalized. The attacker holds every key the server holds and it still does not help. |
| 3 | Ask a witness to co-sign the rebuilt root at the same size | `EQUIVOCATION: already signed size N with root …, now offered …` |
| 4 | Ask a witness to co-sign an altered head below its high-water mark | `ROLLBACK: size N is behind my last signed size M` |
| 5 | Ask a witness to co-sign a larger head with no usable proof | `NO PROOF: …` / `BAD PROOF: the offered tree of size N is not a consistent extension of size M that I signed` |

Then the artefact goes to the standalone verifier, which reports both the witness
disagreement and the anchor contradiction, by name:

```
    HEAD WITNESS DISAGREES: w1 did not sign this head
    anchors: 1/1 signatures ok, 0/1 consistent with the head
      INCONSISTENT: size 4 was externalized with root 45e1740a..., but the head
      at size 7 is not a consistent extension of it -- an entry committed before
      that anchor was altered or dropped
    RESULT: NOT VERIFIED
```

> **The rollback rule needs a witness with a gap.** Rule 1 runs before rule 2, and
> a witness asked twice for the same `(size, root)` returns the signature it
> already gave — on purpose, so a retried request after a dropped response does
> not look like an attack. Rule 2 therefore only fires at a size the witness has
> **never signed** but that sits **below** its high-water mark: the ordinary
> consequence of a witness being down while the log grew. `make tamper` creates
> that condition for real — kills a witness, appends two entries, restarts it,
> appends one more — and prints the gap from the witness's own state file.

---

## Fail-closed ordering

The rule is *log first, release second, fail closed*, and there is no fallback
path that weakens it.

```
BEGIN IMMEDIATE
  ├─ sign the STH with the log key
  ├─ network round trip to every witness, each needing a consistency proof
  │  from the root *that witness* last signed
  └─ if fewer than min_witnesses co-sign:
        ROLLBACK — the leaf is not in the log
        raise STHNotWitnessed
        HTTP 503, and no key material is derived at any point
COMMIT
  └─ only now: unwrap K, re-wrap under the client's ephemeral KEM key
```

- A witness that refuses is a **hard stop**, not a retry. A 409 from a witness is
  mapped to `WitnessUnavailable`, which is mapped to `STHNotWitnessed`, which is
  a 503 with no key.
- `WitnessQuorum.collect` **raises** rather than returning a partial set. There
  is no code path that releases a key because it *nearly* had a quorum.
- The in-process test client returns 503 on this path, matching the HTTP route
  exactly — a client keying off 503 would otherwise have looked correct in tests
  and been wrong on the wire.

---

## Layout

```
logfirst/
  crypto/      pqc (liboqs wrappers), ca, kdf          — the primitives
  ledger/      merkle (RFC 6962), log, witnesses, anchor — the tamper-evident log
  witness/     node (HTTP), signer (the refusal rules)  — the independent co-signers
  authority/   server, store, demo_api                  — the network-facing service
  client/      node                                     — holds ciphertext, never keys
  watermark/   linguistic, tardos, payload, ocr         — the forensic mark
  forensics/   identify, align, investigate, bundle, export
  data/        corpus, deploy, scenario, generate, harness
  sealed.py    the payload frame and the .lfdoc container — bytes in, bytes out
  pdfdoc.py    rendering the two PDFs, and the glyph guard that refuses
  models.py    the wire types (STH, DecryptionRequest, ...)
  proc.py      children that do not outlive a killed parent
verifier/      verify.py, core.py   — imports nothing from logfirst (asserted)
scripts/       demo.py, tamper_demo.py, check_env.py
web/           React + Vite console: distribute/open, leak-check, a container
               reader, and the recipient register. src/container.js parses
               .lfdoc in the browser -- a second implementation of sealed.py,
               pinned to it by tests/test_container_js.py, which runs the JS
               under node against real containers and the malformed cases
tests/         522 tests
```

### The independent verifier

`verifier/` re-implements Merkle hashing and proof folding from scratch rather
than importing the server's. That duplication is the point: a verifier sharing
the code it verifies can only demonstrate self-consistency.
`tests/test_verifier_merkle.py` cross-checks the two implementations over their
whole input space, because a verifier that is *looser* than the server accepts
forgeries and one that is *stricter* fails honest bundles and gets switched off.

```bash
LD_LIBRARY_PATH=$OQS_LIB python -m verifier.verify bundle.json
```

Exit codes distinguish three outcomes: `0` verified, `3` entries sound but **no
anchor was offered** (so a rewritten history would not have been caught), `1`
failed. Folding "not checked" into "verified" would let a script treat an
unchecked history as a verified one.

### The cryptographic opt-in test

`tests/test_crypto_kat.py` compiles liboqs's own NIST-format KAT programs and
compares against pinned response digests. It needs a liboqs **source** tree:

```bash
LOGFIRST_LIBOQS_SRC=/path/to/liboqs pytest tests/test_crypto_kat.py
```

A sibling `../new237` or `../237` checkout is tried automatically. If no source
tree is found the test **skips loudly** rather than silently — a silent skip
would let the strongest evidence in the suite disappear without anyone noticing.

---

## Known limits

- **The formal Tardos bound is unreachable at document lengths this system
  accepts.** 1201 positions required, 185 available at 2400 words. Everything is
  ranking-only. See "Watermark capacity".
- **Watermark extraction needs the canonical document.** The pipeline identifies
  it by TF-IDF cosine, which needs the canonical text in the corpus. A leak of a
  document whose canonical text is gone cannot be traced.
- **The marker density is achievable on template prose, not typical.** A real
  corpus with fewer synonym pairs carries fewer slots and more documents are
  refused.
- **A quorum of witnesses that colludes with the operator can sign a rewritten
  history.** Three independent operators in three administrative domains is the
  mitigation; three processes on one laptop is not.
- **An externalized root nobody kept proves nothing.** The anchor's value is
  entirely in the fact that it left the building.
- **`verify_anchor` proves internal consistency, not authenticity.** It checks
  the record against its own embedded public key. Establishing that the key is
  the real anchor key requires pinning it out of band — the standalone verifier
  takes it as an argument for this reason.
- **The demo serves plain HTTP by default.** A browser cannot satisfy a client
  certificate, so mTLS would lock the front end out of its own API. `--tls` opts
  in; the WARNING on startup says which mode is running.
- **Witness and authority processes only die with a killed starter on Linux.**
  `PR_SET_PDEATHSIG` (`logfirst/proc.py`) is what stops a `kill -9`ed demo or
  test session from leaving a witness holding its port and answering `/cosign`
  from a stale state file. Elsewhere the kernel cannot do this, `die_with_parent`
  returns `None`, and children are orphaned — `WitnessFleet` then refuses to
  start on a busy port with a message that names the cause, which is a
  workaround and says so.
- **A `.lfdoc` header can be edited without breaking decryption.** The AEAD's
  additional data is only the `doc_id`, so the classification, page count and
  pdf hash on the outside of the envelope are a label rather than a fact. The
  manifest inside the encryption is the authority, and `sealed.compare` is what
  holds the two against each other — but a reader who does not call it is
  believing the file's author. Stated in `logfirst/sealed.py` and above.
- **PDF output is reproducible on one machine, not forever.** `pdfdoc.render`
  takes `created` as a required argument rather than reading the clock, so the
  same input gives the same bytes twice — asserted in `tests/test_pdfdoc.py`.
  That claim is scoped to a machine and an fpdf2 version; nothing in the tree
  ever validates a `pdf_hash` by re-rendering, and every hash is taken over the
  bytes that were actually received.
- **The marked PDF rides back in the open response as base64.** That is fine at
  demo lengths (tens of kB) and wrong for a 200-page report. It is *not* fixed
  by caching the marked copy server-side, which would persist a session-bound
  forensic artefact on the authority — exactly what marking on the client side
  avoids.
- **The `.lfdoc` ciphertext is stored hex-encoded in SQLite.** No schema change
  was made for this feature, so a real PDF roughly doubles on disk.
- **The label check on the container screen only works if the authority still
  holds that document.** The screen decides which document an open refers to by
  comparing bytes, so a file whose `doc_id` the authority has never heard of, or
  has since re-distributed, is refused rather than opened — a false negative
  that errs the right way but is still a false negative, and there is nothing on
  the page that can distinguish "older copy" from "edited label".
- **A revocation stops the next open and nothing else.** The authority checks it
  before verifying a signature and before committing anything, so no key is
  released and no ledger entry is written. It cannot recall a copy already
  opened, it destroys no key material (the certificate stays on file, which is
  why reinstating is one flag write), and it does not touch the entries already
  in the ledger naming the opens that happened first.
- **The recipient register is unauthenticated.** `GET /demo/admin/recipients`
  and the revoke/reinstate routes are demo-gated — they exist only when a
  scenario is attached — and carry no auth of their own, on the standing
  assumption that the admin is trusted. That is a boundary the demo draws
  explicitly rather than a claim it makes.

## Requirements

Python ≥ 3.11 (`pyproject.toml`), liboqs with the three FIPS algorithms above,
`fpdf2` (the seal path renders, so there is no mode in which it is absent), and
the system `tesseract` binary for OCR. `scripts/check_env.py` checks all of them
by using them and says what each absence costs.
