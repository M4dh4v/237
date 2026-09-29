---
name: sakshya-honesty
description: Use whenever rendering cryptographic proofs, ledger data, attribution results, verification status, watermark/collusion findings, or the evidence certificate anywhere in the SĀKṢYA frontend. Enforces the non-negotiable honesty rails — present-not-verified, fail-closed-as-guarantee, the caveat system, and the truthful framing of watermark/ledger/collusion. Trigger on any proof, verify, signature, ledger, attribution, certificate, or confidence UI.
---

# SĀKṢYA honesty rails (credibility engine — never break)

A defence evaluator rewards a tool that knows the limit of its own claim. In this product, **the honest limits are presented as rigour, and the real strengths as cinematic.** Never the reverse. These rules are non-negotiable on every proof surface.

## 1. Present-not-verified (the single most important rule)
The browser cannot verify a post-quantum signature. So the UI **never** prints "valid", "verified", or a green check that implies cryptographic verification it did not itself perform. It says **"present, as received"** and defers real verification to the exportable Pramāṇapatra and the standalone `verifier/`. A persistent, calm chip states this wherever proofs are shown, pointing to the independent verifier.

## 2. Fail-closed is a guarantee, not an error
When a key is withheld because the record could not be committed (quorum fail, revoked recipient), render it **green-framed as a demonstrated guarantee**, calm, not alarming: *"The system refused to release the key because it could not write the record."* Reuse the existing `isFailClosed` detection (handles the real `/open` 503 and the wrapped `/demo/open` message). Never a red error box.

## 3. The reserved colors
Verified-green appears **only** where something was genuinely checked. Alert-red appears **only** at a real failure or an unknown source. Neither is ever decoration. The "present" checks on a certificate say **present**, never **verified**.

## 4. The caveat system (small, consistent, never hidden when material)
Reusable caveat component for, at minimum:
- **proves-key-not-human:** *"This proves which key/device/session decrypted the document. It is strong evidence about a person, not a confession."* Fixed, non-removable, on every attribution and on the certificate.
- **ranking-only-collusion:** *"At this document length, the collusion code ranks likely colluders; it does not name one at a formal false-positive bound. Longer documents narrow this."* Show the real numbers (positions available vs ~1201 needed).
- **text-domain-mark:** *"Uploaded files become the document body; the mark rides in the text layer, so text-bearing documents trace best."*
- **simulated-and-disclosed:** witnesses share a host in the demo, transport TLS is classical by design and outside the evidence path, corpus is template prose, device fp is asserted not attested. Collect these in one always-reachable "what this demo simulates, disclosed" panel (evolved from the existing SimulatedPanel).

## 5. Two separated confidences — never one merged number
Attribution results are two-tier, always: **document match** (which source) with its own confidence, and **recipient attribution** (which ledger leaf/recipient) with its own confidence + the proves-key caveat. Conflating them into one score is the dishonest thing most tools do; we never do it.

## 6. Truthful framing of the big claims
- **Ledger / "Bitcoin feeling":** say *"many independent witnesses co-sign a shared, append-only, post-quantum ledger — like a private network where everyone holds the book."* Never say "blockchain", "mining", or "coin". This is literally true of the witness set and survives scrutiny.
- **Copies:** *"reads as an ordinary copy, carries a different hidden fingerprint."* Never "pixel-identical" / "visually identical".
- **Watermark layers:** one robust text-domain (synonym) layer. Do not claim multiple invisible layers.
- **Offline:** the single origin is `127.0.0.1`; the status strip shows OFFLINE. Nothing an upload contains leaves the machine.

## 7. Non-match honesty
Never render a firm certificate for a non-match or low-confidence partial. Those export as an **"inconclusive finding"** report — itself valuable and honest — with specific dead-ends ("couldn't identify the source document" / "identified the document but couldn't recover a usable mark from this fragment; try more text or a cleaner image").

When in doubt: state what was checked and what was not. The tool that discloses its own limits is the one that gets believed.
