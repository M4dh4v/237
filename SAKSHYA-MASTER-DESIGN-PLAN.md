# SĀKṢYA — Master Design Plan
### Frontend reimagining + minimal backend glue for SIH26237 (WESEE / Indian Navy)

> One line: give the same secret file to fifty officers, every copy looks the same, every copy quietly knows who opened it, and the record of who opened it is held by many witnesses so no single admin can rewrite it. This document is the blueprint for the interface that makes that feel real.

---

## 0. How to read this, and the rules I locked with you

This is the design bible. It describes the whole product surface screen by screen, the feel of every interaction, the 3D moments, the copy on the page, and the small backend endpoints we add to make it all work. A separate implementation plan comes later; this one is about *what we are building and why*, in enough detail that nothing important is left to guess.

Four decisions are fixed and everything here obeys them:

1. **The model's real working is untouched.** The cryptography, the ledger, the witnesses, and the watermark logic stay exactly as they are today. We do not add a new invisible-watermark layer, we do not touch the synonym watermark, we do not re-architect the crypto. It works, you have tested it, we leave the engine alone.
2. **Backend change is thin glue only.** We add a handful of small, safe HTTP endpoints so the new frontend can do three things the current one cannot: upload and seal an arbitrary file, enroll a new recipient from the UI, and feed a whole document (not just pasted text or a screenshot) into the trace tool. Nothing in the glue reaches into the crypto or the attribution path. Section 13 lists every endpoint and, just as important, the do-not-touch list.
3. **We dropped the "visually identical" claim on purpose.** The copies differ by word choice, and that is fine. The story becomes "every copy looks like an ordinary copy of the same document, and each one carries a different hidden fingerprint." We never say two copies are pixel-for-pixel identical, because they are not, and a sharp judge would catch it. Honesty here is a feature, not a retreat.
4. **The ledger is sold with the Bitcoin feeling, told truthfully.** The pitch line you like is "a private, post-quantum Bitcoin for documents" and the honest version is "many witnesses each hold the same book of who-opened-what, and changing one copy means fighting all the others." We lean into that image hard in the visuals. We never claim mining, coins, or a public chain. Section 10 is built entirely around making this feel electric without lying.

Everything below serves those four.

---

## 1. What SĀKṢYA actually is, in plain words

A sender seals one document. It goes out to many authorised people. Each person opens their own copy with their own credentials. The moment they open it, three things happen as one event: their own post-quantum signature over "I am opening document X now" is written into a shared, tamper-evident ledger held by several independent witnesses; only after that record is committed does the system hand over the key; and the copy they receive is quietly fingerprinted with a mark derived from that exact ledger entry.

So the copy on a leaker's disk and the ledger record naming them are the same object. Neither can exist without the other. If the document leaks, you drop the leaked copy (or a screenshot of it, or a paragraph pasted out of it) into the trace tool, it reads the hidden mark, looks it up in the ledger, and hands back a record that anyone can verify without trusting the administrator.

The whole thing runs offline. No cloud, no internet, no public blockchain. That is not a limitation we apologise for. For the Navy it is the entire point.

**Why WESEE cares (the lens for every design choice).** WESEE is the Indian Navy's in-house software and combat-systems house. Naval classified networks are air-gapped by mandate. Orders, charts, and technical manuals are distributed to many ships and shore units at once. When one leaks today, the Navy has server access logs that a privileged admin could have edited, and watermarks that are the same on every copy, so attribution collapses to "any of the fifty people who could open it." SĀKṢYA turns that into "this exact person's key opened it at this exact time, here is their own signature, and here is the proof that survives even a compromised administrator." Every screen we design should feel like it belongs on a console in a secure operations room: calm, exact, evidence-grade, and quietly powerful. Not a startup dashboard. An instrument.

---

## 2. Honest gap analysis — what we nail, what we add, what we keep as-is

I read every layer of the backend. Here is the truth of where the system stands against the problem statement, so the frontend can amplify the real strengths and never write a check the engine cannot cash.

### 2.1 What the system genuinely nails (lead with these)

- **Log-before-open (Dvārapāla).** The key is released only after the signed record is committed with a witness quorum. This is the strongest and rarest idea in the whole design. Most teams decrypt first and log after. We flip it, and it is enforced in code, not policy. The frontend must make this ordering *visible and dramatic*.
- **Real NIST post-quantum crypto.** ML-KEM-768 (FIPS 203) for key exchange, ML-DSA-65 (FIPS 204) for signatures, SLH-DSA (FIPS 205) for the long-term anchor, all through liboqs and checked against NIST known-answer vectors. This is real, not decorative.
- **A real tamper-evident ledger with independent witnesses.** RFC 6962 Merkle log, real inclusion and consistency proofs, witnesses that genuinely refuse to co-sign an equivocation, a rollback, or an unproven extension. `make tamper` provokes all of it and the standalone verifier catches it.
- **Attribution that survives the real world.** You saw this yourself. Screenshot it, copy from another account, mess it up, and it still names the source. That is the seed-search trick plus OCR plus alignment plus the self-validating pointer, and it is genuinely impressive.
- **Non-repudiation by the recipient's own key.** The ledger entry is the recipient's own ML-DSA signature over their open request. They cannot later deny it.
- **A verifier that trusts nobody.** A separate program re-derives every check and imports nothing from the main code. This is exactly the "don't trust the admin" property the PS demands.

### 2.2 What the problem statement asks for and where we stand

| PS requirement | Status in code | What the frontend/glue does about it |
|---|---|---|
| Unique invisible forensic watermark at the moment of decryption | Real, linguistic synonym mark derived from the ledger leaf, embedded client-side at open | Show the mark being derived and embedded; show the per-copy difference honestly |
| Watermark specific to each recipient and session | Real, seed = HKDF(leaf hash), two opens differ | Visualise "same doc, two opens, two different marks" |
| Every decrypted copy visually identical, forensically distinct | Copies differ by word choice, not pixel-identical | **We do not claim pixel-identical.** We say "looks like an ordinary copy, carries a different hidden fingerprint" and show the diff as proof of the mechanism |
| Bind each decryption to recipient identity | Real, ML-DSA signature over the request | Render the signed request as a first-class artifact |
| Recipient's own private key signs the record | Real | Show whose key, with the cert chain to the offline CA |
| NIST PQC for key exchange and signatures | Real, ML-KEM-768 + ML-DSA-65 (+ SLH-DSA anchor) | Badge the algorithms everywhere, honestly |
| Immutable audit via blockchain/DLT | Merkle transparency log + multi-witness co-signing (permissioned DLT, not block-chain) | Sell it as "everyone holds the book" with bold chain visuals; call the nodes Sākṣī witnesses |
| No single admin can alter records | Real, witnesses refuse; anchors externalise the root | The Tamper theatre screen and the witness ring make this the emotional peak |
| Extract watermark from a leaked doc | Real for text and screenshot today | **Glue adds whole-document / PDF ingestion** so you can drop the actual leaked file |
| Look up watermark against the ledger | Real, self-validating seed search | Render the lookup as a live trace animation |
| Return a cryptographically verifiable record | Real, evidence bundle + standalone verifier | This becomes the Pramāṇapatra certificate export |
| Fully offline / air-gapped, no cloud KMS, no public chain | Real | Everything vendored, API on 127.0.0.1, an explicit "offline" indicator in the shell |

### 2.3 What we consciously keep imperfect, and how we speak about it

- **Copies are not pixel-identical.** Handled above. We reframe, we do not hide.
- **Tardos is ranking-only at real document lengths.** The formal accusation bound needs ~1201 mark positions; a long document gives ~185. So for collusion the system *ranks* suspects and reports scores, it does not name one colluder with a stated false-positive rate. The frontend must present collusion results as a ranked shortlist with scores and a clear "this ranks, it does not accuse" note. This is the same honesty posture that makes the whole thing credible.
- **The ledger is a transparency log, not literally Bitcoin.** We use the Bitcoin *image* to explain the shared-book idea and never claim blocks, mining, or a public network. If a judge probes, the honest answer ("many independent witnesses co-sign every head, so a rewrite has to beat all of them, and we add post-quantum signatures Bitcoin doesn't have") is stronger than the slogan.
- **Attribution proves key/device/session, not the human.** Baked into the backend as a caveat on every result. The frontend carries it too, every time. This is not weakness. In a courtroom, a tool that knows the limit of its own claim is the one that gets believed.

The design principle that falls out of all this: **make the real strengths cinematic, and make the honest limits look like rigour.** Never the reverse.

---

## 3. The names — our identity, reaffirmed

These come from your PPT build kit and we use them everywhere in the product, not just the deck. Each name is shown with its meaning the first time it appears on a screen ("Dvārapāla, the gate"), then the name alone carries it. The names are not decoration; each one is the function.

| Name | Say it | Meaning | In the product |
|---|---|---|---|
| **SĀKṢYA** | Saak-shya | Evidence, testimony | The whole platform. The word a court uses for evidence, which is what we make. |
| **Sākṣī** | Saak-shee | Witness | Each ledger node. Many witnesses hold the same book. |
| **Dvārapāla** | Dwaa-ra-paa-la | Gatekeeper | The Admin / sealing + gated-open surface. Refuses the key until the record is written. |
| **Guptamudrā** | Gupt-mudra | Hidden seal | The invisible forensic mark placed at open. |
| **Abhijñāna** | Abhi-gyaan | Token of recognition | The identity token inside the mark. The Shakuntala ring that reveals who someone truly is. |
| **Akṣaya Śṛṅkhala** | Akshaya Shrinkhala | Imperishable chain | The tamper-evident post-quantum ledger. |
| **Anveṣaṇa** | An-vesha-na | The investigation | The forensic trace tool. Drop a leak, get a name. |
| **Yantrachihna** | Yantra-chihna | Device mark | The device + session fingerprint bound into each open. |
| **Pramāṇapatra** | Pramaan-patra | Certificate of proof | The exportable, independently verifiable evidence file. |

Two new small names for surfaces the current app does not have, kept in the same spirit:

- **Sūchī** (soo-chee, "the register / index") — the recipient's inbox of documents waiting to be opened.
- **Darśana** (dar-shana, "viewing / audience") — the role-select threshold you pass through after the landing, where you choose to enter as Sender, Recipient, or Investigator.

---

## 4. The look and the feel — one visual language for everything

This is a defence-grade forensic instrument, so the aesthetic is *restrained power*. Dark, quiet, precise, with a single warm accent that points at the one thing that matters on each screen. It should feel closer to an air-traffic or sonar console than to a consumer SaaS app. Empty space is confidence. Motion is meaningful, never decorative for its own sake.

**Palette.**
- Base: near-black `#0A0E14` and a deep navy `#0D1B2A`. The room the instrument sits in.
- Primary: an electric indigo / cyber-blue `#4C6FFF` → `#22D3EE` gradient for structure, lines, and the "system is thinking" states.
- Accent (used once per screen, at the thing that wins the screen): warm gold `#F5B841`. On the Admin screen it points at the "record written before key released" moment. On the trace screen it points at the named recipient.
- Verified green `#3FB950`, tamper/unknown red `#F85149`. These two colours are reserved. Green never appears except where something was actually checked; red never appears except at a real failure or an unknown source. If green shows up as decoration anywhere, we have broken our own rule.
- Text: soft white `#E6EDF3` for primary, muted `#8B949E` for secondary. Never pure white on pure black; it buzzes.

**Type.** One geometric display face for headings — Space Grotesk or Sora — and Inter for body and data. Numbers and hashes in a mono (JetBrains Mono or IBM Plex Mono), because a hash rendered in a proportional font looks like a mistake. All fonts vendored locally, no Google Fonts CDN, because the system is air-gapped and a font fetch that silently fails would be embarrassing on the day.

**Motion.** Lenis for smooth scroll on the landing only. Framer Motion for UI transitions. Three.js / React Three Fiber for the three signature 3D moments (landing, the ledger ring, the trace). The rule: 3D is used where it *explains* something (the shape of the pipeline, the many-witnesses idea, the trace from mark to name), never as a spinning logo. Everything must hold 60fps on a mid laptop with no GPU to speak of, because the demo machine is not guaranteed to be a gaming rig. Every 3D scene has a static, still-beautiful fallback frame so a slow machine degrades to a poster instead of a stutter.

**Truth in the chrome.** A persistent, quiet status strip lives at the top of every authenticated screen: `OFFLINE · 127.0.0.1` (green dot), the ledger tree size and short root, and the witness quorum ("3 of 3 witnesses co-signed the last head"). This strip is doing real work: it is the constant, ambient proof that the thing is alive, air-gapped, and witnessed. Borrowed straight from the current app's honest `StatusBar`, upgraded.

**The present-not-verified rule (kept from today's app).** The browser cannot verify a post-quantum signature. So the UI never prints "valid" or "verified" for anything it did not itself check. It says "present, as received" and defers real verification to the Pramāṇapatra export and the standalone verifier. This one rule is a huge credibility signal to a technical judge and we keep it religiously.

---

## 5. Information architecture — the shape of the whole thing

```
  ┌─────────────────────────────────────────────────────────────┐
  │  THE LANDING  (Pravāha, "the flow")                           │
  │  3D scroll journey: the problem → the gate → the mark →       │
  │  the many witnesses → the trace → the proof. Ends at a door.  │
  └───────────────────────────────┬─────────────────────────────┘
                                   │  "Enter"
  ┌───────────────────────────────▼─────────────────────────────┐
  │  DARŚANA — the threshold / role select                        │
  │  Three doors: Sender · Recipient · Investigator               │
  │  (a demo "god mode" toggle reveals all three at once for the  │
  │   judges, clearly labelled as a demo convenience)             │
  └───────┬───────────────────┬───────────────────────┬─────────┘
          │                   │                       │
  ┌───────▼──────┐   ┌────────▼────────┐   ┌──────────▼─────────┐
  │  DVĀRAPĀLA   │   │  SŪCHĪ           │   │  ANVEṢAṆA          │
  │  Sender /    │   │  Recipient inbox │   │  Investigator /    │
  │  Admin       │   │  + open + keep   │   │  trace tool        │
  │  (seal,      │   │                  │   │  (paste / drop     │
  │  distribute, │   │                  │   │  image / upload    │
  │  manage      │   │                  │   │  whole doc → name) │
  │  recipients) │   │                  │   │                    │
  └───────┬──────┘   └────────┬─────────┘   └──────────┬─────────┘
          │                   │                        │
          └─────────┬─────────┴────────────┬───────────┘
                    │                       │
       ┌────────────▼───────────┐  ┌────────▼──────────────┐
       │ AKṢAYA ŚṚṄKHALA        │  │ PRAMĀṆAPATRA          │
       │ the ledger, always     │  │ the exportable proof  │
       │ reachable as a shared  │  │ certificate (from any │
       │ panel / overlay        │  │ open or trace result) │
       └────────────────────────┘  └───────────────────────┘
```

Three role dashboards, two shared surfaces (the ledger and the proof export) that any role can pull up. The landing is a one-time cinematic; a returning user can skip straight to Darśana. For the judges there is a clearly-labelled demo control that lets one person drive all three roles from one screen without logging in and out, because in a five-minute demo you cannot afford three separate logins. It is labelled "demo convenience — a real deployment separates these by credential" so we are never caught pretending it is the security model.

---

## 6. The landing — Pravāha ("the flow")

The landing is one continuous scroll-driven 3D journey. It exists to make a stranger *feel* the idea in ninety seconds before they read a single feature. It tells the story of one secret document: how it goes out, how the gate works, how the mark is born, why many witnesses matter, and how a leak gets traced home. Lenis drives a buttery scroll; each "station" is a scene that assembles as you arrive and dissolves as you leave. The camera never cuts; it flows, because the product's whole thesis is that everything is one connected event.

The through-line object is a single sheet of paper — one document — that we follow the entire way down. It is always on screen in some form. That continuity is the point: one file, one journey, one chain of proof.

### Station 0 — The hook (full viewport, before any scroll)

Black. Center screen, one sheet of paper rendered in 3D, faintly glowing at the edges, slowly breathing. Over it, in Space Grotesk, the line resolves letter by letter:

> **Every copy looks the same. Every copy knows who opened it.**

Below, small and mono: `SĀKṢYA · evidence, in Sanskrit`. A quiet down-chevron pulses. The status strip is already there, top: `OFFLINE · 127.0.0.1 · ledger 0 leaves`. First impression in three seconds: this is serious, this is Indian, this is about a document that remembers.

Behind the paper, almost subliminal, fifty faint identical ghost-copies fan out in a shallow arc — the "fifty suspects" — so the problem is present before it is named.

### Station 1 — The problem (scroll 1)

As you scroll, the fifty ghost copies slide forward and become a crowd of identical faceless silhouettes, each holding an identical page. One of them, indistinguishable, pulses red for a heartbeat and then hides back in the crowd. Text, right-aligned, sparse:

> One file. Fifty readers. It leaks. **Every copy is identical, so everyone is equally guilty, and no one can be named.**

The red pulse is the leaker, and the whole point is you *cannot tell which one*. This is the ache the product resolves. Hold it for one beat of scroll, uncomfortable on purpose.

### Station 2 — The gate, Dvārapāla (scroll 2, first signature 3D moment)

The crowd falls away. The single sheet returns and approaches a gate — rendered as a tall, thin, luminous doorway made of two vertical light-bars, like a security scanner. A recipient figure (abstract, a glowing outline) steps up holding the sealed file. Here we make the ordering *physical and undeniable*:

1. The figure presses their hand to the gate. A signature glyph (their ML-DSA key) flares.
2. That glyph flies *sideways* into a growing stack of blocks to the left (the ledger) and locks in with a satisfying settle. The block goes gold for an instant — this is the accent moment of the whole landing.
3. **Only now** does the gate open. A key materialises and flows into the document. The order is unmistakable: record first (left), key second (right).

Text:

> **Dvārapāla, the gate.** The key is never released until the recipient's own post-quantum signature is written to the ledger. There is no opening without a trace.

If we get one thing to stick in a judge's memory, it is this scene. The sideways-then-open motion *is* the pitch. Everything else supports it.

### Station 3 — The mark, Guptamudrā (scroll 3)

The opened document now fills more of the frame. We zoom into the paper until individual words are legible (real-looking body text). As the ledger block from station 2 pulses, a thread of light runs from that block into the page, and a scatter of words across the page quietly shimmer and *change* — a synonym here, a synonym there — each shimmer leaving a faint gold underline that fades. We are watching the mark being written, derived from the ledger entry.

Then the camera pulls back and splits: two copies of the same page side by side, "opened by Alice" and "opened by Bob," and we highlight that the marked words differ between them. Honest and clear:

> **Guptamudrā, the hidden seal.** The copy is fingerprinted with a mark grown from that exact ledger entry. Two people open the same file and receive two different hidden marks. It reads as an ordinary copy. It is not.

Note the copy: "reads as an ordinary copy," never "pixel-identical." We keep the decision from section 0.

### Station 4 — The many witnesses, Akṣaya Śṛṅkhala (scroll 4, second signature 3D moment)

This is the "Bitcoin feeling," told true. The single ledger stack from station 2 lifts and the camera orbits it. Then it *multiplies*: the same chain of blocks appears in several places around a ring, each glowing node a Sākṣī witness, and thin lines of light connect them all, pulsing in sync. When a new block lands (an open happening), it appears in all of them at once and they each flash a co-signature.

Then the dramatic beat: a single node darkens and a hand (an "admin," rendered menacingly) tries to *edit* one block in it — the block turns red. Instantly the other witnesses reject it: red lines snap toward the tampered node, it is quarantined and pushed out of the ring, and the ring closes over the gap. The honest, powerful line:

> **Akṣaya Śṛṅkhala, the imperishable chain.** The book of who-opened-what is held by many independent witnesses at once. Like a private network where everyone keeps the same ledger, changing one copy means fighting all the others — and every signature here is post-quantum. No single administrator can rewrite history.

This is the scene that earns the Bitcoin line without lying: "everyone keeps the same ledger" is exactly what the witnesses do. We never say blocks are mined or that there is a coin.

### Station 5 — The trace, Anveṣaṇa (scroll 5, third signature 3D moment)

Cut to the aftermath. A crumpled, leaked page tumbles into frame — visibly a photo of a screen, a little skewed, a little noisy, to signal "this came from the wild." A magnifier sweeps across it and the hidden marked words light up one by one, assembling into a glowing token — the Abhijñāna. That token then flies to the witness ring from station 4, threads through the blocks, and locks onto exactly one — which expands to reveal a name card: the recipient, the time, the device, the signature.

> **Anveṣaṇa, the investigation.** Drop the leaked copy, a screenshot, or even a single pasted paragraph. We read the hidden token, match it to the ledger, and return the exact recipient — with proof anyone can check.

The emotional arc completes: the crowd of identical suspects from station 1 reappears faintly behind the name card, and this time forty-nine of them dim to grey while one stays lit in gold. From "any of fifty" to "this one, with proof."

### Station 6 — The proof, and the door (scroll 6, the CTA)

The name card seals itself into a certificate — the Pramāṇapatra — with a wax-seal press animation and a row of green "present" checks (signature present, inclusion proof present, witness quorum present, anchor present). A final line:

> Built to run on a disconnected machine. No cloud. No internet. No public chain. **SĀKṢYA.**

Below it, three doors slide up — **Enter as Sender · Recipient · Investigator** — which *is* the Darśana threshold. The landing pours directly into the app. Scrolling was the story; the door is the product.

### Landing engineering notes

- Built with React Three Fiber + Drei, scroll bound with Lenis + a scroll-progress hook, section reveals with Framer Motion. GSAP ScrollTrigger is an acceptable alternative if the team is more fluent in it; pick one and commit.
- The single sheet, the crowd, the gate, and the block-ring are the only heavy meshes; keep total draw calls low, instance the crowd and the blocks (fifty silhouettes and a few dozen blocks are instanced, not fifty separate meshes).
- Everything is deterministic and offline: no external asset fetches, textures baked and vendored, fonts local.
- **Fallback:** a `prefers-reduced-motion` and a low-power path that renders each station as a still, composed poster with the same copy, so the story survives on a weak machine or a nervous demo laptop. The narrative reads even as six static frames.
- A persistent "skip to app" affordance top-right for the fifth time you show it to someone.

---

## 7. Sender dashboard — Dvārapāla ("the gatekeeper")

This is where an authorised sender turns a plain document into a sealed, per-recipient-traceable artefact and hands it out. The design brief from void: clean, uncluttered, upload any file, generate a doc in-app, pick who's included, create new recipients inline, a cool 3D encryption animation, and classification. The whole screen should feel like a *control room for one deliberate act*, not a busy admin panel.

### 7.0 Layout and mood

A calm, dark, three-zone workspace. Left: a slim vertical rail (source → recipients → classification → seal), which doubles as a progress spine — you always know which of the four steps you are on. Center: the stage, where the current step's work happens and where the 3D seal animation plays. Right: a collapsible "ledger pulse" strip showing the live chain head and the last few opens, so the sender feels connected to the same book the landing showed. Generous whitespace, one gold accent at a time, no more than one primary button per view.

### 7.1 Step 1 — The source (what to seal)

One drop target that accepts everything, presented as a single large, inviting panel: **"Drop a file, or start one here."** Four ways in, as quiet tabs on that panel:

1. **Upload any file** — PDF, image (PNG/JPG), or text/markdown. Drag-drop or browse. On drop, a thumbnail/preview renders (PDF first page, image itself, or text head). This is a *new* backend glue endpoint (section 13); it ingests the file, stores it as the document body to be sealed.
2. **Generate in-app** — a clean rich-text editor (title + body) for typing or pasting a memo on the spot. Useful for a live demo where no file is handy. Also feeds the same seal path.
3. **Curated corpus** — the existing sealed corpus picker, kept exactly as it works today. A searchable list of the pre-built documents. This is the safe, always-works demo path and must remain first-class.
4. **Paste text** — quick single-field paste for a fast one-off.

Whatever the source, the outcome is identical downstream: a document body enters the pipeline. Show a small honest note under uploads: *"Uploaded files become the document body; the mark is carried in the text layer, so text-bearing documents trace best."* This quietly sets expectations without breaking the flow, and it is true to how the watermark works today (linguistic, text-domain).

A preview pane on the right of the stage shows the chosen document with a subtle watermark-capacity meter: *"~185 mark positions available in this text"* — turning a limitation into a visible, credible number. Green when ample, amber when thin, with a tooltip explaining more text = stronger, formally-bounded attribution.

### 7.2 Step 2 — The recipients (who is included)

A grid of recipient cards, each a glowing identity chip: name, role, key fingerprint (short), status (active / revoked). The sender selects who this document goes to by toggling cards — selected cards lift and gain a gold rim. A running count reads *"sealing for 12 recipients."*

Two creation affordances, inline, no page change:

- **+ New recipient** — a compact inline form (display name, optional role/unit). On submit it calls the create-recipient glue endpoint (section 13), which enrolls them and generates their PQC keypair server-side; the new card animates into the grid, pre-selected. This satisfies void's "create new recipient names during encryption."
- **Manage** — per card, a small menu to revoke/reinstate (existing endpoints). Revoked cards go grey and cannot be selected; a revoked recipient who tries to open later hits the fail-closed path, which we showcase elsewhere.

Search and filter across the top when the list grows. Bulk select ("all active"). Keep it uncluttered: cards are quiet until hovered.

### 7.3 Step 3 — Classification

A single, deliberate control: a classification selector rendered as a set of banded chips — e.g. `UNCLASSIFIED · RESTRICTED · CONFIDENTIAL · SECRET` — styled with a defence-appropriate restraint (thin colored top-band per level, no garish fills). Selecting a level stamps a corresponding banner onto the document preview (top and bottom, as real classified docs carry). This is presentational and metadata-level; it rides along in the sealed container's header and shows up later in the recipient's inbox and in the evidence certificate. It makes the whole thing *feel* like real defence tooling, which matters for WESEE.

Optional second control on this step: a short free-text "handling caveat" line (e.g. "deal-team only") that also stamps and travels with the record.

### 7.4 Step 4 — The seal (the cool 3D moment)

The payoff. A single primary button: **Seal & Distribute.** On press, the stage clears to the encryption animation:

- The document contracts to a glowing core.
- For each selected recipient, a strand of light spins out and wraps the core — the ML-KEM key-encapsulation, one wrap per recipient — until the core is cocooned in a woven lattice (the broadcast encryption to many). Recipient count = strand count, visibly.
- The lattice compresses into a single faceted crystal — the `.lfdoc` container — which drops with weight onto a pedestal. A soft *thunk*.
- Around it, the four PQC/ledger facts light up as small certified badges: `ML-KEM-768` · `ML-DSA-65 ready` · `witness quorum n` · `offline`.

Crucially, the animation must *tell the truth about sequencing*: sealing/distribution happens now, but the **ledger write happens at open, not here**. So the seal animation ends with the crystal sitting *unopened* and a caption: *"Sealed. Nothing is written to the ledger until a recipient opens it — that is the gate."* This keeps the log-before-open invariant honest and actually makes the story stronger (the sender armed it; the recipient's own act is what commits).

After seal: a clean receipt view — document id, recipient list, classification, container hash — with **Download container** and **Copy manifest** actions, and a soft prompt: *"Switch to a recipient to open it"* (deep-links to the Sūchī dashboard for the live demo).

### 7.5 Sender dashboard — always-visible honesty and state

- If the backend is unreachable, the seal button is disabled with the exact hint ("start it with `python scripts/demo.py --serve`"), reusing the existing ApiError copy.
- The ledger-pulse strip shows the real head and updates on poll; if a witness is down and quorum can't be met, the strip says so and the seal step warns *before* you try, not after.
- Never claim the container is unbreakable; the badge says "sealed with ML-KEM-768," and a tooltip gives the honest one-liner ("the body is useless without an authorised open").

### 7.6 Extra ideas (offered, not assumed)

- **Distribution manifest export** — a one-page PDF/JSON of "who this went to, when, under what classification," useful as a paper trail. Cheap glue over existing data.
- **Recipient groups** — save a set of recipients as a named group ("Bridge Watch") to reselect quickly. Pure frontend convenience over the recipient list.
- **Dry-run capacity check** — before sealing, show the watermark capacity/expected attribution strength for the chosen document so the sender knows if the text is too short to trace well. Reads honestly and is genuinely useful.

---

## 8. Recipient dashboard — Sūchī ("the register / inbox")

Where a recipient receives sealed documents, opens them (which is the act that writes to the ledger and marks their copy), and reads or exports them. void's brief: an inbox that updates with newly received documents, decrypt, screenshot/copy. The emotional target is quieter than the sender's control room — this should feel like a secure personal reader, calm and trustworthy, with one dramatic beat at the moment of opening.

### 8.1 Identity and layout

Top-left, a "you are" chip: recipient name, role, short key fingerprint, active/revoked state. This anchors the whole screen — everything a recipient does is bound to *this* identity, and that binding is the product's spine. Two-pane layout: left, the inbox list; right, the reader.

### 8.2 The inbox list (updates with new documents)

A vertical list of received documents, newest first. Each row: title, sender, classification band, arrival time, and a state pill:

- **Sealed** — received, not yet opened. Gold-rimmed, inviting. This is the call to action.
- **Opened** — already decrypted by you; shows when, and a tiny "marked" glyph indicating your copy carries your fingerprint.
- **Unavailable** — e.g. you were revoked; greyed, with an honest reason on hover.

The list polls the backend and animates new rows in with a soft slide + a one-time pulse, so during a live demo the sender seals on one screen and the recipient literally watches it *arrive* on another. A small "N new" badge on the tab. This is the "inbox that updates" void asked for, and it makes the two-dashboard demo choreography land.

### 8.3 Opening a document — the gate, from the recipient's side

Click a sealed row → the reader pane shows the sealed state: classification banner, title, sender, and a single **Open** button with a short honest sub-line: *"Opening signs this with your key and writes it to the ledger before the content unlocks."*

On **Open**, a compact version of the gate animation plays *in the reader pane* (not a full takeover — this is a workspace, not a show):

1. Your signature glyph flares.
2. It flies to a small ledger-head widget in the corner, which ticks up one leaf and shows the co-signatures landing.
3. The document then unlocks and renders.

If quorum fails or you're revoked, the open **fails closed**: the content never appears, and the pane shows the fail-closed state as a *demonstrated guarantee*, not an error — green-framed "the system refused to release the key because it could not write the record," reusing `isFailClosed`. This is one of the strongest honest moments in the product and it lives here.

### 8.4 The reader (opened document)

A clean document reader: classification banners top and bottom, the body text, sender and open-time metadata. Two deliberate actions, because void specifically wants the leak-and-trace loop to be demonstrable:

- **Copy text** — copies the body to clipboard. The point: the copied text still carries the hidden mark, so a paste into the trace tool later still attributes. A tiny note: *"Copied. Your hidden mark travels with the text."*
- **Screenshot / save image** — renders the visible document to a PNG the user can save (canvas capture). This is the "took a photo of the screen" path the forensic tool is built to survive. Note: *"Even a screenshot carries the mark."*

These two buttons are the bridge to the Anveṣaṇa demo, and they're the features void loved ("attribution works even after screenshot/copy/mess-up"). Make them prominent but not loud.

A "marked copy" affordance on the reader: a subtle, toggleable overlay that faintly highlights *where* the mark lives in the text (for explanation during a pitch), off by default so the normal reading experience looks like an ordinary document. Honest and pedagogically great.

### 8.5 Empty, revoked, and offline states

- **Empty inbox:** a calm placeholder — *"No documents yet. When a sender seals one for you, it appears here."*
- **Revoked mid-session:** the identity chip flips to revoked, sealed items become unavailable, and any open attempt fails closed with the honest reason. Great to demo live (revoke on the sender side, watch it lock here).
- **Offline:** same reusable backend-unreachable panel and hint.

### 8.6 Extra ideas (offered, not assumed)

- **"Who else received this"** toggle, if policy allows — shows the recipient that a document was broadcast to N people, reinforcing the many-suspects framing from their own side.
- **Read receipt back to sender** — since opening already writes a ledger leaf, the sender's ledger-pulse strip can already reflect "opened by X"; surface that as a gentle confirmation. No new backend needed.

---

## 9. Investigator dashboard — Anveṣaṇa ("the investigation")

The leak-tracing tool: give it a leaked artefact, it returns the recipient with proof. void's brief: paste text, drop images, AND (new) upload whole documents. The mood here is forensic and deliberate — a lab bench, not a magic wand. The whole design ethos is *honesty as rigour*: it never accuses without a confidence score, it separates "which document" from "which recipient," and every claim carries the caveat that it proves which key/device/session decrypted, not which human held it.

### 9.1 The bench — three ways to submit evidence

One prominent submit zone with three modes, presented as tabs on a single "evidence intake" panel:

1. **Paste text** — a textarea for a leaked paragraph or whole body. Existing path. Best case for extraction.
2. **Drop an image** — screenshot or photo of a screen. Runs OCR (real tesseract) → text → the pipeline. Existing path; show the OCR'd text back so the investigator sees what was read.
3. **Upload a whole document (NEW)** — PDF or document file. This is the new feature: a glue endpoint (section 13) extracts the text layer (PDF text extract, or OCR fallback for scanned/image PDFs), then runs the identical forensic pipeline. Multi-page supported; show per-page extraction status.

On submit, an honest "what we're doing" progress trail plays step by step, mirroring the real pipeline so judges see the method, not a black box:

`read text → identify which document (TF-IDF) → align to the master (LCS) → extract hidden soft-bits → search for a self-validating seed → match to a ledger entry → assemble evidence`

Each step ticks green as it completes, or stops honestly if it can't (e.g. "couldn't identify the source document with confidence" → stops, explains, suggests more text).

### 9.2 The finding — separated confidences, never one number

The result is deliberately *two-tier*, because conflating them is the dishonest thing most tools do:

- **Document match** — "this leak is from document *Fleet Movement Order 14*," with its own confidence (how sure we are which source it is).
- **Recipient attribution** — "the hidden mark decodes to a ledger entry naming *Recipient: Lt Sharma, opened 12:04, device fp …*," with its *own* confidence, and the honest caveat line beneath: *"This proves which key/device/session decrypted the document. It is strong evidence about a person, not a confession."*

When the mark is fully recovered and self-validates against the ledger, present it boldly: the name card, gold, with the four green "present" proof checks (signature, inclusion proof, witness quorum, anchor). When it's partial, say so — show what was recovered and rank candidates rather than naming one.

### 9.3 The collusion case — Tardos, told honestly

If the evidence looks like a *mix* of several copies (collusion — two recipients combined their documents to blur the mark), the tool switches to its honest ranking mode:

- It presents a **ranked list of suspected colluders** with scores, not a single name.
- A clear, prominent honest banner: *"At this document length, the collusion code ranks likely colluders; it does not name one at a formal false-positive bound. Longer documents narrow this."* — with the real numbers (positions available vs positions needed for the formal Tardos bound). This turns a genuine limitation into a display of exactly the kind of rigour a defence evaluator wants to see.

### 9.4 The proof — into the ledger and out as a certificate

When an attribution lands, the result links straight into the shared Akṣaya Śṛṅkhala ledger view (section 10): the matched leaf highlights inside the witness ring, and you can inspect its inclusion proof and the witness co-signatures — the "anyone can check this" moment. From here, **Export evidence** produces the Pramāṇapatra certificate (section 11).

### 9.5 States and honesty rails

- **No match:** honest, specific dead-ends — "couldn't identify the source document," or "identified the document but couldn't recover a usable mark from this fragment; try more text or a cleaner image" — never a fake result.
- **Present-not-verified:** the browser shows the evidence but cannot itself verify PQC signatures; a persistent chip says so and points to the standalone `verifier/` for independent checking. This is the app-wide rule, and it matters most here.
- **Offline:** same reusable panel/hint.

### 9.6 Extra ideas (offered, not assumed)

- **Side-by-side diff** — show the leaked text against the identified master with the recovered mark positions highlighted, so the investigator sees the physical basis of the attribution.
- **Evidence log** — a running list of past traces this session, each re-openable, so an investigator can work a batch.
- **Confidence explainer** — a "why this score" expander that shows the soft-bit recovery quality, alignment coverage, and seed self-validation, in plain language.

---

## 10. The shared ledger — Akṣaya Śṛṅkhala ("the imperishable chain")

This is the cross-cutting visual that appears (at different sizes) in the landing, the sender's pulse strip, the recipient's open widget, and full-screen from the investigator's result. It is the single most important "cool + honest" artefact in the app, because it carries void's "Bitcoin feeling" sell without telling a lie. Design principle: **make the many-witnesses truth look as exciting as a blockchain, because it genuinely is one — just an honest, permissioned, post-quantum one.**

### 10.1 The full view — the witness ring

Center: a chain of blocks, each block one opened-document leaf, rendered as faceted gold-edged tiles linked head-to-tail (the Merkle sequence). Around them, arranged in a ring, several glowing nodes — the Sākṣī witnesses — each visibly holding *its own copy of the same chain*. Thin light-lines connect every witness to every other, pulsing gently in sync: the shared book.

When a new open happens (live or replayed), a new block forms at the head and *appears in every witness at once*, and each witness flashes its co-signature onto it. The block only "sets" (goes solid gold) once the quorum has signed — you watch consensus happen. Caption, honest and confident:

> Every witness keeps the same ledger. A document is only counted as opened once enough of them have co-signed it. Like a private network where everyone holds the book — no single administrator can quietly change the past.

This is the exact framing locked in section 0: it *feels* like "a Bitcoin-style network where everyone has the ledger," and every word of it is literally true of the witness set. We never say "blockchain," "mining," or "coin"; we say "witnesses co-signing a shared, append-only, post-quantum ledger," which sounds just as strong and survives scrutiny.

### 10.2 The tamper beat (interactive)

A deliberate "try to cheat it" control: **Attempt to alter a block.** On press, one witness node is shown being edited by a bad admin — its block turns red. The other witnesses immediately detect the divergence (their copies disagree), reject the altered node, and it's visibly quarantined; the consistency proof between the honest witnesses stays intact. A line:

> Change one copy and it no longer matches the others. The witnesses refuse it. History cannot be rewritten by one hand.

This maps to the real equivocation/rollback/extension refusals in the witness code — we're dramatising a real mechanism, not inventing one.

### 10.3 Inspecting a block

Click any block → a detail card: leaf index, the recipient/open it records, timestamp, the leaf hash, the inclusion proof path (shown as the Merkle branch lighting up toward the root), the witness co-signatures, and any external SLH-DSA anchor that covers it. Everything is real data from the existing `/ledger/*`, `/witnesses`, `/anchors` routes. The present-not-verified chip applies: the browser displays these proofs; the standalone verifier is what independently checks them.

### 10.4 Anchors — the outside witness

A small "published anchors" shelf shows roots that were signed out to an external record (SLH-DSA), framed as: *"even the witnesses' shared history is periodically nailed to an outside marker, so rewriting the past would have to contradict a record this system doesn't control."* Reuses the existing anchors data already rendered in today's LedgerFooter.

### 10.5 Embedded forms

- **Sender pulse strip:** a condensed horizontal chain-head + last-few-opens, live-polling.
- **Recipient open widget:** a tiny head counter that ticks up when you open, with the co-signatures landing.
- **Investigator link:** the matched leaf highlighted in the full ring with its proof path lit.

All three are the same component at different scales and data density, so the chain a recipient sees and the chain the investigator inspects are provably the same object — consistent with today's "render the head with identical code" discipline in the codebase.

---

## 11. The evidence certificate — Pramāṇapatra ("the certificate of proof")

The exportable, shareable artefact that closes a trace. When an investigator lands an attribution, they export a Pramāṇapatra: a single, self-contained document that a third party (a court, a commanding officer, an auditor) can read and independently verify. This is the product's *deliverable to the outside world*, so it has to be beautiful, complete, and scrupulously honest.

### 11.1 What it contains

- **Header:** SĀKṢYA seal, certificate id, generation time, classification of the source document, and a bold present-not-verified honesty stamp explaining that the certificate presents evidence and how to verify it independently.
- **The finding:** which document, which recipient, when opened, device/session fingerprint — with the two separated confidence figures (document match, recipient attribution) shown as clear numbers, never merged.
- **The caveat, in plain language, prominent, not buried:** *"This certifies which cryptographic key/device/session decrypted the document. It is strong evidence about a person's key, not proof of who physically held it."* This is a fixed, non-removable line. It is what makes the certificate trustworthy.
- **The proof chain:** the ledger leaf, its inclusion proof, the witness co-signatures with their public-key fingerprints, and the covering anchor. Enough for someone to re-run the checks.
- **How to verify:** explicit instructions and the standalone `verifier/` reference, so the recipient of the certificate doesn't have to trust SĀKṢYA's own UI.
- **Collusion honesty:** if the case was a ranking (Tardos), the certificate says so and presents the ranked candidates with the formal-bound caveat, rather than a single name.

### 11.2 Form and export

Rendered on screen as a wax-sealed certificate (the seal-press animation from the landing's finale), then exported as a **PDF** (primary, for humans) and a **JSON evidence bundle** (secondary, for machines/the verifier). The PDF uses the docx/pdf skill discipline for a genuinely professional layout; the JSON is exactly what the standalone verifier consumes.

This mirrors the existing independent "evidence bundle" the forensics pipeline already produces — the Pramāṇapatra is its presentable face, not a new source of truth.

### 11.3 Honesty rails

- Never render a certificate for a non-match or a low-confidence partial as if it were a firm attribution; those export as an "inconclusive finding" report instead, which is itself valuable and honest.
- The green "present" checks say *present*, not *verified*, everywhere — consistent with the app-wide rule.

---

## 12. Cross-cutting components, states, and the honesty layer

These carry the whole app's credibility and are shared across all three dashboards. Build them once, reuse everywhere.

### 12.1 The status strip (always visible)

A thin top strip present on every screen: `OFFLINE · 127.0.0.1:8443 · ledger N leaves · quorum m/n · witnesses up`. It is the constant reminder that this runs air-gapped and that the ledger is live. It turns red-honest when the backend is unreachable (reusing the existing reachable/unreachable logic and copy) and shows the fail-closed state as a first-class, non-alarming condition when it fires.

### 12.2 The fail-closed pattern

Fail-closed is never an "error box." It is rendered green-framed as a *demonstrated guarantee*: "the system refused to release the key because it could not commit the record." Reuse the existing `isFailClosed` detection (which already handles both the real `/open` 503 and the wrapped `/demo/open` message). This appears in the recipient open flow and anywhere a key would be released.

### 12.3 Present-not-verified

A persistent, calm chip wherever cryptographic proof is shown: the browser *presents* signatures and proofs but cannot itself verify PQC; independent verification is the standalone `verifier/`. Never fake a green "verified" the browser can't back up. This is the single most important honesty rule and it is non-negotiable in every proof surface.

### 12.4 The caveat system

A reusable caveat component (small, consistent, never hidden in a tooltip when it's material) for: proves-key-not-human, ranking-only-collusion, text-domain-mark (uploads trace best when text-bearing), and simulated-and-disclosed items (witnesses share a host in the demo, transport TLS is classical by design and outside the evidence path, corpus is template prose, device fp asserted not attested). A single "what this demo simulates, disclosed" panel — evolved from today's SimulatedPanel — lives in an always-reachable "about the honesty of this build" view.

### 12.5 Loading, empty, and motion

- Loading = purposeful, never a bare spinner: show the pipeline step names ticking (investigator) or the seal strands forming (sender), so waiting reinforces the method.
- Empty states speak plainly and point to the next action.
- Motion respects `prefers-reduced-motion`: every 3D scene has a composed static fallback with identical copy, so nothing fails on a weak or nervous demo machine.

### 12.6 Darśana — the role threshold

The three-door chooser (Sender / Recipient / Investigator) that the landing pours into and that is reachable any time from the status strip. In a demo, switching roles is one click, which is what makes the seal-on-one-screen / arrive-on-another / trace-on-a-third choreography flow.

---

## 13. Backend — thin glue only (with an explicit do-not-touch list)

Locked constraint: **do not touch the actual working of the model.** No changes to crypto, ledger, witness, watermark, or forensics logic. Everything below is a thin adapter/route layer that feeds existing pipeline entry points. If a feature can't be built as glue, it is out of scope for now.

### 13.1 Do NOT touch (hard boundary)

- `logfirst/crypto/` — ML-KEM / ML-DSA / SLH-DSA, HKDF seed derivation. Untouched.
- `logfirst/ledger/` — RFC 6962 Merkle log, inclusion/consistency proofs, STH. Untouched.
- `logfirst/witness/` — co-signing, equivocation/rollback/extension refusals, quorum. Untouched.
- `logfirst/watermark/` — synonym substitution, RS coding, Tardos codeword. **Untouched** (this is the "keep it how it works now" decision; no new invisible layer).
- `logfirst/forensics/` — OCR, TF-IDF, LCS, soft-bit extraction, seed search, evidence bundle. Logic untouched; we only *feed* it new input types.
- `verifier/` — stays independent, imports nothing from logfirst.
- The log-before-open invariant and the seed = HKDF(committed leaf hash) binding. Sacred.

### 13.2 New glue endpoints (adapters only)

All new routes live in the demo/authority API layer alongside the existing ~22 routes, call existing pipeline functions, and add no new cryptographic behaviour.

1. **`POST /demo/source/upload`** — accept an uploaded file (PDF / image / text/markdown), extract a text body (PDF text extract; OCR fallback via the *existing* tesseract path for scanned/image input; text passes through), and register it as a sealable document body using the *existing* seal/distribute path. Returns a document id + preview + the watermark-capacity number (positions available), computed from existing watermark utilities. Pure adapter: file-in → text-body → existing pipeline.

2. **`POST /demo/source/compose`** — accept `{title, body}` typed in-app and register it as a sealable document via the same existing path. Trivial adapter.

3. **`POST /demo/admin/recipients/create`** — enroll a new recipient (display name, optional role), generating their PQC keypair via the *existing* key-generation/enrollment functions. Returns the new recipient card data. (Companion to the existing revoke/reinstate routes.)

4. **`POST /leakcheck/upload`** (or extend `/leakcheck`) — accept a whole uploaded document (PDF/doc) for the trace tool, extract its text (text layer or OCR fallback, existing tesseract), then run the *existing, unchanged* forensic pipeline. Supports multi-page. This is the one genuinely new user-facing capability void asked for, and it's still just an input adapter in front of the same forensics.

5. **(Optional) `GET /demo/source/{id}/capacity`** — return watermark capacity/expected-attribution-strength for a chosen document, from existing watermark math, to power the sender's honest capacity meter and dry-run check.

6. **(Optional) `POST /evidence/certificate`** — render the Pramāṇapatra PDF/JSON from an *existing* forensics evidence bundle. Presentation adapter over data that already exists; no new proof logic.

### 13.3 Reused as-is (no change)

`/demo/state`, `/demo/documents`, `/demo/distribute`, `/demo/open`, `/demo/leak`, `/demo/documents/{id}.lfdoc`, `/demo/admin/recipients`, `/demo/admin/revoke`, `/demo/admin/reinstate`, `/leakcheck`, `/leakcheck/example/{kind}`, `/ledger/head`, `/ledger/entry/{i}`, `/ledger/entries`, `/witnesses`, `/health`, `/anchors`. The new frontend talks to all of these through the existing `web/src/api.js` contract (thrown ApiError, isFailClosed, isUnreachable), which we keep and extend with the handful of new methods above.

### 13.4 Constraints on the glue

- No new cryptographic primitives, no new watermark channel, no change to what gets committed or when.
- Uploaded/composed documents flow through the *same* seal → open → mark path as the curated corpus; they are not a special case downstream.
- File handling stays offline and local; nothing an upload contains leaves the machine.
- Every new endpoint fails closed and returns the same error shape the frontend already understands.

---

## 14. Tech stack and how to build the 3D reliably, offline

### 14.1 Stack

- **React + Vite** (keep the existing setup).
- **React Three Fiber + @react-three/drei** for the 3D scenes (declarative three.js that fits React; easier to maintain than raw three.js).
- **Lenis** for smooth scroll on the landing.
- **Framer Motion** for 2D reveals, page/role transitions, and UI motion. (If the team prefers GSAP ScrollTrigger for the scroll-bound landing, that's an acceptable single alternative — choose one scroll-animation approach and commit; don't mix.)
- **Keep cytoscape only if** a 2D graph is still wanted somewhere; the ledger is moving to the R3F witness-ring, so cytoscape likely retires. Don't add new heavy deps beyond the above.

### 14.2 Offline / air-gapped discipline (non-negotiable)

- **Vendor everything.** All npm deps installed and bundled by Vite; no CDN imports at runtime. Fonts (Space Grotesk, Sora, Inter, a mono) downloaded and served locally. Textures/models baked and shipped in the repo.
- No external network calls anywhere in the frontend. The only origin is `127.0.0.1:8443`.
- Verify by building, disconnecting, and loading: nothing should 404 or hang.

### 14.3 Making the 3D dependable on a demo laptop

- Keep meshes few and **instanced** (the crowd of suspects, the ledger blocks). Bake lighting where possible; avoid heavy real-time shadows.
- Cap pixel ratio, lazy-mount 3D scenes per route (don't run the landing's scene while in a dashboard), and dispose on unmount.
- **Every 3D scene has a static fallback** (composed poster + same copy) triggered by `prefers-reduced-motion` or a manual "lite mode" toggle in the status strip. The pitch must survive a weak GPU.
- Test the whole thing on the actual demo machine early, not the night before.

### 14.4 Structure

- `web/src/scenes/` — R3F scenes (Landing stations, WitnessRing, SealAnimation, GateAnimation), each with a `*.static.jsx` fallback.
- `web/src/dashboards/` — Dvārapāla, Sūchī, Anveṣaṇa.
- `web/src/components/` — shared honesty layer (StatusStrip, FailClosed, PresentNotVerified, Caveat, SimulatedPanel), reused ledger widget at three scales.
- `web/src/api.js` — extended with the new glue methods; existing contract preserved.

---

## 15. PS requirement coverage matrix

How the redesigned SĀKṢYA maps to SIH26237's literal asks, and where we're honest about the gap. "Where shown" points at the surface that demonstrates it.

| PS requirement | Status | Where shown | Honest note |
|---|---|---|---|
| Per-recipient forensic watermark generated at decryption | Met | Recipient open (Guptamudrā), landing station 3 | Linguistic/text-domain mark; unchanged from today |
| Watermark bound to recipient identity via their own private-key signature | Met | Gate animation, ledger leaf detail | ML-DSA-65 signature; seed = HKDF(committed leaf) |
| Non-repudiation of the decryption event | Met | Recipient open + ledger co-signatures | Proves key/device/session, not the human (stated) |
| Immutable, tamper-evident ledger no single admin can alter | Met | Akṣaya Śṛṅkhala witness ring + tamper beat | RFC 6962 log + multi-witness quorum; not block-chain-mined |
| Blockchain / DLT | Met-as-permissioned-DLT | Witness ring, "everyone holds the book" framing | Told as witnesses co-signing a shared ledger; never called a coin/mined chain |
| Given a leak, extract mark → look up ledger → name recipient with verifiable proof | Met | Anveṣaṇa trace + Pramāṇapatra | Two separated confidences; verifier is independent |
| NIST PQC for key exchange + signatures | Met | Badges, ledger detail, certificate | ML-KEM-768, ML-DSA-65, SLH-DSA anchors |
| Fully offline / air-gapped, no cloud KMS, no public chain | Met | Status strip (OFFLINE), stack discipline | Vendored assets, single localhost origin |
| Copies "visually identical" | Not met, reframed | Landing station 3 copy, capacity meter | Dropped by decision; framed as "reads as an ordinary copy, carries a different hidden mark" |
| Ingest a leak from paste / image / whole document | Met (upload is new) | Anveṣaṇa three intake modes | Whole-document upload is the one new capability; adapter over existing forensics |
| Collusion resistance | Partial, honest | Anveṣaṇa ranking mode, certificate | Tardos ranks colluders; formal FPR bound needs longer docs (real numbers shown) |
| Multiple watermark layers (PPT claimed 3) | Reframed to 1, honestly | Guptamudrā copy | Only the word-choice layer exists; PPT should say one robust text-domain layer |

The strategy: everything the system genuinely does is presented cinematically and confidently; the four honest gaps (visual identity, Tardos bound, DLT-vs-Bitcoin, key-vs-human) are presented as rigour, which is exactly what a defence evaluator rewards.

---

## 16. Open questions to confirm (nothing assumed)

None of these block starting; they're the places I made a reasonable call and want your yes/no before it hardens.

1. **Role auth for the demo** — is switching between Sender / Recipient / Investigator just a UI role-select (fast, great for demoing), or do you want a light login per role? I've assumed frictionless role-select via Darśana.
2. **Classification levels** — I used `UNCLASSIFIED · RESTRICTED · CONFIDENTIAL · SECRET`. Want the exact Navy/WESEE labels instead, or is this fine for the pitch?
3. **Whole-document upload for the trace tool** — for scanned/image PDFs we fall back to the existing OCR; for text PDFs we extract the text layer. Good? (Text-bearing docs trace best, as noted.)
4. **Scroll-animation library** — R3F + Lenis + Framer Motion is my default; happy to switch the landing's scroll-binding to GSAP ScrollTrigger if your team is more fluent there. Preference?
5. **Retire cytoscape?** — the ledger becomes the 3D witness ring, so cytoscape likely goes. Any 2D graph you want kept?
6. **PPT reconciliation** — the deck currently claims 3 watermark layers and leans hard on "Bitcoin." Do you want me to note exact edits for the PPT (one text-domain layer; "witnesses hold a shared post-quantum ledger" phrasing) as part of this, or keep that separate?
7. **Certificate output** — Pramāṇapatra as PDF (humans) + JSON (verifier). Want a .docx variant too?

---

*End of master design plan. Implementation plan (build order, milestones, task breakdown) is a separate document to follow when you're ready.*
