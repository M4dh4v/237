# logfirst — front end

A four-tab React app over the logfirst demo API: **Distribute & open**,
**Leak check**, **Open a .lfdoc**, and **Recipients**. It is mostly a viewer for
the backend's responses, and the one place it is not — the container reader —
is the one place that needs saying out loud. See "What this UI does NOT do".

## Running it

Two processes. The backend first:

```bash
python -m logfirst.authority.server --no-tls
```

`--no-tls` is not optional for a browser front end. The authority serves mTLS
by default, and it sets `ssl_cert_reqs=2`, which means it demands a client
certificate during the handshake — a browser cannot satisfy that from a
`fetch`, and the failure appears as an opaque network error rather than
anything that mentions certificates. Plain HTTP on `127.0.0.1:8443` is the
only configuration this UI can talk to.

Then the front end:

```bash
cd web
npm install
npm run dev      # http://localhost:5173
```

Vite proxies `/demo`, `/leakcheck`, `/ledger`, `/witnesses`, `/health`,
`/documents`, `/open` and `/anchors` to `http://127.0.0.1:8443`, so the app
calls same-origin relative URLs. That is deliberate rather than convenient: the
API sets no CORS headers, so a cross-origin call from a page served anywhere
else is blocked by the browser with no useful diagnostic.

`npm run build` produces `dist/`. The built bundle contains no base URL, so it
works behind any origin that can reach the backend.

### If the backend is not running

Every screen says so specifically, names the address it tried, and prints the
command to start it. Nothing renders placeholder data and nothing spins
forever. This is the expected failure mode for a first run, not an edge case —
and note that the dev proxy answers `/demo/state` with its own `500 text/plain`
when nothing is listening upstream, so the app treats a 5xx *with no JSON
`detail`* as "not reachable" rather than as an application error.

### If the server has no scenario attached

`/demo/*` and `/leakcheck*` are registered only when the app is built with a
scenario. A server started without one answers `/demo/state` with
`{"available": false, "reason": "..."}`, and the app says so instead of showing
empty controls.

## The four tabs

### Distribute & open

Pick a document, tick the recipients to grant, choose a classification, and
distribute. Distributing seals the document to the authority's KEM key — it
grants nobody the ability to read it, and the note the API returns says so.

#### The two files

Distributing produces a file you can download, and opening produces a second
one. They are different in kind, and the UI is worded so the difference is not
blurred.

**`DOC-0000.lfdoc`** — the distribution artefact, available as soon as the
document is sealed. It is **not a PDF**: no viewer opens it, `%PDF` does not
occur anywhere inside it, and `file` calls it data. It is the document
encrypted under a content key that only the authority's ML-KEM private key can
unwrap. It carries that key *wrapped to the authority's public key*, which is
what makes the file a complete description of itself and completely useless on
its own: it is a locked box and the lock, with the key held elsewhere. The
button says all of this next to itself rather than in a tooltip, because the
file's uselessness is the claim being demonstrated.

**`DOC-0000-…-marked.pdf`** — available only *after* a successful open, because
the watermark inside it is derived from that open's ledger entry, which does
not exist until someone opens the document. This one is a real PDF: it opens in
any viewer, and its text is the marked text, so a printout, a `pdftotext`, or a
retyped paragraph still attributes to the session that produced it.

Neither is downloaded automatically. A file that saves itself is a file whose
provenance is invisible, and the marked copy's whole value is that it is tied
to the ledger entry rendered above it — so each has a button, and the marked
one is labelled with the entry index it is bound to and the sha256 of the bytes
you are about to receive.

When a document is too short to carry a mark, `pdf_marked` comes back false and
the panel says so instead of offering a "marked PDF": the file would be
byte-identical to the plaintext and calling it forensic evidence would be a
quiet lie. The distributed PDF is offered either way — it is the recipient's
copy, it just is not evidence of anything.

Then pick one granted recipient and open it. Opening is the event the whole
system exists for, and it is rendered in the order it happens:

1. **The signed request the client built.** The recipient's own signature is
   over these exact fields.
2. **The entry as it entered the ledger** — index and leaf hash, with the leaf
   bytes available in full.
3. **The tree head it was committed under**, with one row per witness.
4. **The mark derived from that entry** — every substitution as
   `position · original → marked`, and the plaintext and delivered text side by
   side. The seed that chose the substitutions is derived from the leaf hash
   shown two panels above; the positions themselves come from the document's
   payload plan (`pointer_bits` + `tardos_bits`).

The server's `caveat` string is rendered at the top of the result, at body
size, not as small print.

**Fail-closed is a feature here, not an error.** If the ledger cannot be
extended, the authority releases no key and returns 503. The UI renders that as
`REFUSED: the ledger could not be extended, so no key was released` and
explains why, with the server's own reason string. The status bar shows whether
fail-closed has fired this session — as a state, on screen permanently, not as
a transient alert.

### Leak check

Paste text, drop in a screenshot, or use one of the three example buttons, then
run. There is also a collapsible control that generates a real leak from the
demo session via `POST /demo/leak`, which yields the demo's ground truth without
the reader having to supply an artefact. The example buttons return it too, so
the "reveal what actually happened" box is not reserved for the path that
requires knowing the control is there.

What the result screen is careful about:

- **The status banner is worded per status**, one of seven, and each says what
  was and was not established. `attributed` leads with the caveat rather than
  with the word "attributed": what was identified is a key, a device and a
  session, and nothing in the ledger records which person was operating it.
- **Two confidences, never blended.** `document.confidence` ("this text came
  from DOC-0000") and `watermark.confidence` ("the mark decoded") are different
  quantities answering different questions. They get separate labels and
  separate bars, and there is no combined score anywhere.
- **A candidate is never a bare name.** Every row carries the collusion score,
  the threshold, a bar showing whether it crossed, and the server's per-
  candidate notes.
- **`ranking-only` is stated near the table**, with both numbers: the document
  carries `tardos_positions` where the formal accusation bound needs
  `tardos_required`. The scores rank suspects; a ranked list is a lead, not a
  finding.
- **The verification panel is framed as the server's statement**, because that
  is what it is — see below.
- **`no-watermark` presents `ledger_sessions` as context**, headed "these
  recipients decrypted this document — any of them could be the source", not as
  a suspect list.
- **`single-mark` is separate from `no-watermark` on purpose.** One candidate's
  score clearing the accusation threshold while nobody else comes near it is the
  shape of *one person's* mark, not of finding nothing — and the pointer that
  would have named their session did not survive. Reporting that as
  "no-watermark" would tell a reader the opposite of what the pipeline found, so
  it gets its own status, its own wording, and the candidate's score.
- **`unidentified` does not print an empty candidate table**, because an empty
  table reads as "nobody did it", which is not what was established.
- **`attribution-unverified` is named as the tamper case** and says plainly
  that no attribution is reported.
- **Server `notes` are in a collapsed panel**, available without dominating the
  page.
- **The `simulated` list is rendered on both tabs.** It is the sentence that
  says the witnesses are separate processes on one machine rather than separate
  operators on separate hosts, which is the entire reason witness co-signing is
  supposed to mean something. It belongs on screen, not in a README.
- **Demo ground truth is in its own box**, shown only after a check has run,
  and labelled as the demo's intention rather than as evidence. It is never
  merged into the result. All three example buttons carry it, not just the
  "generate a leak" control, so it is available on the path a first-time reader
  takes as well as the one they have to go looking for.

### Open a .lfdoc

Tab 3. Give it a container — dropped, chosen, or fetched from the authority —
and it does three things in order, keeping them visibly separate because they
have very different strengths:

1. **Reads the label**, in the browser, with no key. Doc id, classification,
   cipher, page count, hashes, the section table, and the wrapped key envelope.
   The panel then says plainly that none of it is authenticated: the AEAD binds
   only the `doc_id`, so the rest is a claim the file's author wrote.
2. **Checks the file against the authority's copy** of the `doc_id` in that
   label, by hashing both here. This is the load-bearing step. The open is
   performed by the authority on *its* document, chosen by an id out of an
   unauthenticated header, so without this comparison an edited label would get
   you a PDF from a document you were never sent — and nothing on screen would
   say so. The open button stays disabled until the two hashes match.
3. **Opens**, then compares the label with the manifest that came out of the
   decryption. This is the first point at which the label is checkable rather
   than merely readable, and a field-by-field disagreement is reported as the
   finding it is.

A completed open renders through the *same* `OpenResult` component as tab 1, so
the receipt, the ledger entry, the tree head and the mark are the same panels in
both places. The opened copy is previewed inline, labelled with the entry that
produced it. The container itself is never previewed — it is not a document.

### Recipients

Tab 4. Every recipient the authority knows, read from its own store rather than
the CA's file, with the certificate serial and algorithms, the CA signature
check, grants and open counts, and the two device fingerprints side by side —
the one enrolment recorded and the one the last request asserted.

The only control is **revoke**, and it asks for confirmation that says what it
does not do: it stops the next open, it cannot recall a copy already opened, and
it destroys no key material. Reinstating is one flag write, which is why the
certificate is still on file. There is deliberately no way to enrol anyone here:
certificates are issued by the CA offline, and a route that minted identities
would put identity issuance on the network-facing service.

---

## What this UI does NOT do

The honest list. Each of these is a real limitation, and each is why some
panel is worded the way it is.

- **It cannot verify a signature in the browser.** Recipients, the log and the
  witnesses all sign with ML-DSA-65; the anchors use SLH-DSA. Neither is
  available in WebCrypto, and re-implementing lattice verification in
  JavaScript would put an unverifiable amount of unverified code between the
  reader and the claim. The one thing it does compute is a **SHA-256**, in the
  container reader, and that is not a weakening of this: a hash is available in
  WebCrypto, and the comparison it feeds is between two byte strings rather than
  a claim about a key. So the UI reports **what arrived**, never "valid":
  per witness, "co-signed this head" (a signature value was present) or "did
  not sign". The panel is labelled *signatures shown as received — the
  standalone verifier re-checks them out-of-band*. The check of record is
  `verifier/`, run against the ledger's public outputs, not this page.
- **It does not recompute anything cryptographic.** Leaf hashes, inclusion
  proofs, Merkle roots and the document fingerprint are displayed as returned.
  It does not check that a proof folds the leaf into the root.
- **It does not re-derive the watermark.** The recovered positions and the
  seed are shown as the server reported them. A wrong extraction would be
  rendered faithfully.
- **The verification panel is the server grading its own work.** The booleans
  in it come from the investigating process. The UI says so on the panel. It is
  a useful summary and it is not independent.
- **It does not contact the witness nodes.** "Co-signed this head" is a
  statement about the response body, not evidence that a witness is reachable,
  honest, or independent of the log — and in this deployment they are processes
  on one machine anyway.
- **It does not authenticate the backend.** Plain HTTP on loopback, no
  certificate pinning. Anything that can bind that port is believed. The UI
  cannot tell a genuine authority from a local impostor, and does not claim to.
- **It stores nothing.** No history, no saved investigations, no local
  persistence; a reload loses everything. Nothing is written to browser storage.
- **It does no image processing.** Screenshots are sent to the server as-is;
  OCR happens there.
- **It does not check the downloaded PDFs.** The sha256 shown beside the marked
  PDF is the value the *same response* reported, so it identifies the file
  against this page and nothing more. Nothing here hashes the bytes after they
  arrive, and a server that reported a hash for a file it did not send would
  not be caught by this screen.
- **It does not decide anything.** Every classification, status and score on
  screen is a value the server returned. Where the UI adds words, it adds them
  to say what the value does *not* establish. The container reader's sha256
  comparison is the one check the page performs rather than reports — and it is
  a check on *which file this is*, not on whether anything in it is true.
- **The container reader cannot decrypt, and does not pretend to.** The content
  key is wrapped to the authority's public key, so nothing here could open a
  `.lfdoc` even with the file in hand. Everything it shows before an open is the
  file's own label, which the AEAD does not cover and anyone holding the file
  can edit.
- **The container reader's doctored-label check can produce a false negative.**
  It refuses to enable the open unless the dropped file matches the authority's
  container for the `doc_id` in its header, so a copy from an older
  distribution of the same document is refused too. The page cannot tell that
  case from an edited label, and says so rather than guessing.

## Files

```
web/
  index.html            no external fonts, scripts or stylesheets
  vite.config.js        dev proxy; 127.0.0.1 rather than localhost
  src/
    main.jsx
    App.jsx             tabs, demo-state polling, status bar wiring
    api.js              every fetch; the only place errors are classified
    container.js        the .lfdoc header, parsed in the browser. A second
                        implementation of logfirst/sealed.py, kept in step by
                        tests/test_container_js.py, which runs this file under
                        node against real containers and the malformed cases
    download.js         base64 → Blob, Content-Disposition, and the object URL
                        that has to be revoked
    format.js           truncation, percentages, leaf parsing
    styles.css          one stylesheet
    components/
      StatusBar.jsx     tree size, root, witness count, fail-closed state
      DistributeOpen.jsx  tab 1, including the staged open result
      LeakCheck.jsx     tab 2, including the seven status banners
      OpenContainer.jsx tab 3: the local read, the hash comparison, the open
      Users.jsx         tab 4: the register, revoke and reinstate
      LedgerView.jsx    reusable STH / entry / verification / simulated panels
```
