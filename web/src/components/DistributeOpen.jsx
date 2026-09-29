import { useEffect, useMemo, useRef, useState } from 'react'
import { api, isFailClosed, isUnreachable } from '../api.js'
import { base64ToBlob, saveBlob } from '../download.js'
import { shortHex, when, parseLeaf } from '../format.js'
import { SthPanel, LedgerEntryPanel, NotesPanel } from './LedgerView.jsx'

const CLASSIFICATIONS = ['UNCLASSIFIED', 'CONFIDENTIAL', 'SECRET', 'TOP SECRET']

export default function DistributeOpen({
  demoState,
  onSessionChanged,
  onFailClosed,
  onOpenSucceeded,
  onError,
}) {
  const [documents, setDocuments] = useState(null)
  const [docsError, setDocsError] = useState(null)
  const [docId, setDocId] = useState(null)
  const [selected, setSelected] = useState([])
  const [classification, setClassification] = useState('SECRET')

  const [distributing, setDistributing] = useState(false)
  const [distributed, setDistributed] = useState(null)
  const [distributeError, setDistributeError] = useState(null)
  const [containerBusy, setContainerBusy] = useState(false)
  const [containerError, setContainerError] = useState(null)

  const [openRecipient, setOpenRecipient] = useState(null)
  const [opening, setOpening] = useState(false)
  const [opened, setOpened] = useState(null)
  const [openError, setOpenError] = useState(null)
  const [refused, setRefused] = useState(null)

  useEffect(() => {
    let cancelled = false
    api
      .documents()
      .then((d) => {
        if (cancelled) return
        setDocuments(d.documents || [])
        setDocsError(null)
        // Preselect the first document so the screen is not a wall of empty
        // controls on load, but do not preselect recipients: choosing who can
        // decrypt a classified document should cost a deliberate click.
        if (d.documents?.length) setDocId((cur) => cur ?? d.documents[0].doc_id)
      })
      .catch((e) => {
        if (cancelled) return
        setDocsError(e)
        onError?.(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [onError])

  const doc = useMemo(
    () => documents?.find((d) => d.doc_id === docId) || null,
    [documents, docId],
  )

  const recipients = demoState?.recipients || []

  function toggleRecipient(id) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  }

  async function doDistribute() {
    setDistributing(true)
    setDistributeError(null)
    setDistributed(null)
    // A new distribution invalidates whatever was opened before: the previous
    // open's receipt refers to an older ledger state, and leaving it on screen
    // next to the new grants invites reading them as one artefact.
    setOpened(null)
    setRefused(null)
    setOpenError(null)
    setOpenRecipient(null)
    try {
      const res = await api.distribute({
        doc_id: docId,
        recipients: selected,
        classification,
      })
      setDistributed(res)
      onSessionChanged?.()
    } catch (e) {
      setDistributeError(e)
      onError?.(e.message)
    } finally {
      setDistributing(false)
    }
  }

  async function doDownloadContainer() {
    setContainerBusy(true)
    setContainerError(null)
    try {
      const { blob, filename } = await api.downloadContainer(distributed.doc_id)
      // The server's own name wins when it sent one; it is the same name curl
      // would produce, which keeps the demo's two paths agreeing on disk.
      saveBlob(blob, filename || `${distributed.doc_id}.lfdoc`)
    } catch (e) {
      setContainerError(e)
      onError?.(e.message)
    } finally {
      setContainerBusy(false)
    }
  }

  async function doOpen() {
    setOpening(true)
    setOpenError(null)
    setOpened(null)
    setRefused(null)
    try {
      // include_pdf asks for both PDFs to ride back in this response. They are
      // *not* downloaded here: a file that saves itself hides the ledger entry
      // it came from, and the entry is the point. Each one gets a button below.
      const res = await api.open({
        doc_id: docId,
        recipient_id: openRecipient,
        mark: true,
        include_pdf: true,
      })
      setOpened(res)
      onSessionChanged?.()
      // A successful open retires the fail-closed flag: the bar reports the
      // state of the system now, and leaving it lit after the ledger recovered
      // would turn a status indicator into a permanent alarm.
      onOpenSucceeded?.()
    } catch (e) {
      if (isFailClosed(e)) {
        // Not an error path in the usual sense: this is the guarantee firing.
        // It gets its own state so it can be rendered as a demonstrated
        // outcome, with the ledger's own reason, instead of a red failure box.
        setRefused(e.detail)
        onFailClosed?.(e.detail)
      } else {
        setOpenError(e)
        onError?.(e.message)
      }
    } finally {
      setOpening(false)
    }
  }

  const granted = distributed?.grants || []

  return (
    <div className="tab-body">
      <section className="panel">
        <h3>1 · Seal and distribute</h3>
        <p className="note">
          The document is sealed to the authority's KEM key. No recipient key is
          involved at this step and no recipient holds a key share, so
          distribution alone grants nobody the ability to read anything.
        </p>

        {docsError ? (
          <p className="bad">{docsError.message}</p>
        ) : documents === null ? (
          <p className="muted">loading documents…</p>
        ) : documents.length === 0 ? (
          <p className="muted">no documents are available in the corpus</p>
        ) : (
          <>
            <div className="field">
              <label htmlFor="doc">document</label>
              <select
                id="doc"
                value={docId || ''}
                onChange={(e) => setDocId(e.target.value)}
              >
                {documents.map((d) => (
                  <option key={d.doc_id} value={d.doc_id}>
                    {d.doc_id} · {d.words} words · {d.sealed ? 'sealed' : 'not sealed'}
                  </option>
                ))}
              </select>
            </div>

            {doc ? (
              <div className="docmeta">
                <span>
                  {doc.words} words · {doc.slots} markable slots
                </span>
                <span>
                  Tardos positions {doc.tardos_positions} of {doc.tardos_required} required
                </span>
                <span>
                  guarantee: <strong>{doc.guarantee}</strong>
                </span>
                {doc.preview ? <p className="preview">“{doc.preview}…”</p> : null}
              </div>
            ) : null}

            <div className="field">
              <span className="field-label">recipients to grant</span>
              <div className="checks">
                {recipients.length === 0 ? (
                  <span className="muted">no recipients in this scenario</span>
                ) : (
                  recipients.map((r) => (
                    <label key={r} className="check">
                      <input
                        type="checkbox"
                        checked={selected.includes(r)}
                        onChange={() => toggleRecipient(r)}
                      />
                      {r}
                    </label>
                  ))
                )}
              </div>
            </div>

            <div className="field">
              <label htmlFor="cls">classification</label>
              <select
                id="cls"
                value={classification}
                onChange={(e) => setClassification(e.target.value)}
              >
                {CLASSIFICATIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <button
              className="primary"
              onClick={doDistribute}
              disabled={distributing || !docId || selected.length === 0}
            >
              {distributing ? 'sealing…' : 'Distribute'}
            </button>
            {selected.length === 0 ? (
              <p className="note">select at least one recipient — grants are recorded per recipient</p>
            ) : null}
          </>
        )}

        {distributeError ? (
          <div className="result result-bad">
            <h5>distribution failed</h5>
            <p className="mono">{distributeError.detail || distributeError.message}</p>
          </div>
        ) : null}

        {distributed ? (
          <div className="result">
            <h5>sealed and granted</h5>
            <dl className="kv">
              <dt>document</dt>
              <dd>{distributed.doc_id}</dd>
              <dt>content hash</dt>
              <dd>
                <code title={distributed.doc_hash}>{shortHex(distributed.doc_hash, 20, 12)}</code>
              </dd>
              <dt>granted</dt>
              <dd>{distributed.grants?.join(', ') || '—'}</dd>
            </dl>
            {distributed.note ? <p className="note">{distributed.note}</p> : null}

            <div className="download">
              <button onClick={doDownloadContainer} disabled={containerBusy}>
                {containerBusy ? 'fetching…' : `Download ${distributed.doc_id}.lfdoc`}
              </button>
              <p className="note">
                This file is <strong>not a PDF</strong>. No viewer opens it, and{' '}
                <code>%PDF</code> does not appear anywhere inside it — it is the
                document encrypted under a content key that only the authority's
                KEM private key can unwrap. The file carries that key{' '}
                <em>wrapped</em>, which is why it can be handed out at all: it is
                a locked box and the lock, with the key held elsewhere.
              </p>
              {distributed.container_bytes ? (
                <p className="note">
                  {distributed.container_bytes.toLocaleString()} bytes ·{' '}
                  {distributed.pages ?? '—'} page PDF inside ·{' '}
                  {distributed.pdf_hash ? (
                    <>
                      pdf sha256{' '}
                      <code title={distributed.pdf_hash}>
                        {shortHex(distributed.pdf_hash, 20, 12)}
                      </code>
                    </>
                  ) : null}
                </p>
              ) : null}
              {containerError ? (
                <p className="bad">{containerError.detail || containerError.message}</p>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <h3>2 · Open as a granted recipient</h3>
        {granted.length === 0 ? (
          <p className="muted">
            distribute the document first. Opening is only meaningful for a
            recipient this session actually granted, because the grant is what
            the authority checks before it releases a key.
          </p>
        ) : (
          <>
            <div className="field">
              <span className="field-label">open as</span>
              <div className="checks">
                {granted.map((r) => (
                  <label key={r} className="check">
                    <input
                      type="radio"
                      name="open-recipient"
                      checked={openRecipient === r}
                      onChange={() => setOpenRecipient(r)}
                    />
                    {r}
                  </label>
                ))}
              </div>
            </div>
            <button
              className="primary"
              onClick={doOpen}
              disabled={opening || !openRecipient}
            >
              {opening ? 'requesting…' : 'Open'}
            </button>
            <p className="note">
              Opening is what commits an entry: the client signs a decryption
              request, the authority appends it to the ledger, and only then is
              the content key wrapped to the session's one-time KEM key.
            </p>
          </>
        )}

        {openError ? (
          <div className="result result-bad">
            <h5>open failed</h5>
            <p className="mono">{openError.detail || openError.message}</p>
            {openError.status ? <p className="note">HTTP {openError.status}</p> : null}
          </div>
        ) : null}

        {refused ? (
          <div className="result result-refused">
            <h5>REFUSED: the ledger could not be extended, so no key was released</h5>
            <p className="note">
              This is the fail-closed path working as designed. The authority had
              no valid, witness-co-signed head to commit this request against, so
              it released nothing rather than release something that could not
              later be attributed. There is no watermark to show for this session
              because no decryption happened.
            </p>
            <p className="mono">{refused}</p>
          </div>
        ) : null}
      </section>

      {opened ? (
        <OpenResult
          opened={opened}
          witnesses={demoState?.witnesses}
          witnessPubs={demoState?.ledger_publics?.witness_pubs}
          quorum={demoState?.min_witnesses}
        />
      ) : null}
    </div>
  )
}

/**
 * Everything a successful open produced, in the order it was produced.
 *
 * The numbering is the point. The watermark seed is derived from the leaf
 * hash, which is derived from the request, which is what the recipient signed
 * — so the sections are laid out as a chain of derivation rather than as a set
 * of equal cards. Read top to bottom, each stage names what it was derived
 * from; a reader who wants to know where the mark came from can walk it back
 * to the signature.
 */
/**
 * The receipt for one open: the signed request, the ledger entry, the tree head
 * and the mark.
 *
 * `startAt` exists because these panels are numbered as a continuation of
 * whatever came before them, and they are rendered on two different tabs now:
 * on "distribute & open" they follow panels 1 and 2, while on "open a .lfdoc"
 * they follow a different three-step sequence. The default keeps tab 1 exactly
 * as it was; the other tab passes the number its own sequence ended on, so that
 * one page never shows two different panels numbered the same.
 */
export function OpenResult({
  opened,
  witnesses,
  witnessPubs,
  quorum,
  startAt = 3,
}) {
  const receipt = opened.receipt || {}
  const plan = receipt.marking_plan || {}
  const { parsed: leaf, raw: rawLeaf, error: leafError } = parseLeaf(opened.ledger_entry?.leaf)
  const req = leaf?.request || leaf
  const caveat = opened.caveat || receipt.caveat

  return (
    <>
      <section className="panel panel-caveat">
        <h3>Caveat — read this before the attribution below</h3>
        <p className="caveat-text">
          {caveat || 'the server returned no caveat string for this open'}
        </p>
      </section>

      <section className="panel">
        <h3>{startAt} · The signed request the client built</h3>
        <p className="note">
          This is the object the recipient's own post-quantum key signed. The
          signature is over these exact fields; the ledger entry is this same
          object, so the attribution and the recipient's signature are the same
          artefact rather than two things that must be kept in agreement.
        </p>
        {leafError ? (
          <p className="bad">{leafError}</p>
        ) : null}
        {req ? (
          <dl className="kv">
            <dt>recipient</dt>
            <dd>{req.recipient_id}</dd>
            <dt>document</dt>
            <dd>{req.doc_id}</dd>
            <dt>nonce</dt>
            <dd>
              <code title={req.nonce}>{shortHex(req.nonce, 16, 10)}</code>
            </dd>
            <dt>timestamp</dt>
            <dd>{when(req.timestamp)}</dd>
            <dt>device fingerprint</dt>
            <dd>
              <code title={req.device_fp}>{shortHex(req.device_fp, 16, 10)}</code>
            </dd>
            <dt>ephemeral KEM key</dt>
            <dd>
              <code title={req.ephemeral_kem_pub}>
                {shortHex(req.ephemeral_kem_pub, 16, 10)}
              </code>
            </dd>
            <dt>signature</dt>
            <dd>
              {req.sig ? (
                <code title={req.sig}>{shortHex(req.sig, 20, 12)}</code>
              ) : (
                <span className="absent">not present</span>
              )}
            </dd>
          </dl>
        ) : rawLeaf ? (
          <pre className="pre-wrap">{rawLeaf}</pre>
        ) : null}
      </section>

      <section className="panel">
        <h3>{startAt + 1} · The entry as it entered the ledger</h3>
        <p className="note">
          The envelope below is the ledger's own record of where this request
          landed. This page shows it as received; it does not recompute the leaf
          hash.
        </p>
      </section>

      <LedgerEntryPanel entry={opened.ledger_entry} title="Ledger entry" />

      <SthPanel
        sth={receipt.sth}
        witnesses={witnesses}
        witnessPubs={witnessPubs}
        quorum={quorum}
        title="Tree head this entry was committed under"
      />

      {receipt.inclusion_proof?.length ? (
        <section className="panel">
          <h4>Inclusion proof</h4>
          <p className="note">
            The sibling hashes that fold this leaf into the root above. The proof
            is shown so it can be taken away and checked; it is not checked here.
          </p>
          <ol className="proof">
            {receipt.inclusion_proof.map((h, i) => (
              <li key={i}>
                <code title={h}>{shortHex(h, 24, 12)}</code>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="panel">
        <h3>{startAt + 2} · The mark derived from that entry</h3>
        <p className="note">
          The seed that chose the marked words is{' '}
          <code title={receipt.watermark_seed}>
            {receipt.watermark_seed ? shortHex(receipt.watermark_seed, 16, 10) : '—'}
          </code>
          , derived from the leaf hash shown above. The marked positions are
          exactly the <strong>{plan.pointer_bits ?? '—'} pointer positions</strong>{' '}
          plus the <strong>{plan.tardos_bits ?? '—'} Tardos positions</strong> of
          this document's payload plan
          {plan.total_bits != null ? <> ({plan.total_bits} bits total)</> : null}. The
          plan is a property of the document, not of the recipient; what the seed
          chooses is <em>which word</em> goes in each position.
        </p>

        {plan.guarantee === 'ranking-only' ? (
          <p className="note note-warn">
            The plan reports the guarantee <strong>ranking-only</strong>: this
            document carries {plan.tardos_required ?? '—'} required Tardos
            positions and {plan.tardos_positions ?? '—'} are available. Collusion
            scores therefore rank suspects; they do not meet the formal
            accusation bound.
          </p>
        ) : null}

        <div className="marks">
          {opened.mark_diff?.length ? (
            <table className="table">
              <caption className="table-caption">
                Every substitution this session made. These positions and words
                are what a recovered mark is matched against.
              </caption>
              <thead>
                <tr>
                  <th>position</th>
                  <th>original</th>
                  <th>marked</th>
                </tr>
              </thead>
              <tbody>
                {opened.mark_diff.map((m, i) => (
                  <tr key={i}>
                    <td>{m.position}</td>
                    <td>
                      <span className="strike">{m.original}</span>
                    </td>
                    <td>
                      <span className="marked-word">{m.marked}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">this session made no substitutions</p>
          )}
        </div>
      </section>

      <section className="panel">
        <h4>The copy the recipient keeps</h4>
        <div className="side-by-side">
          <div>
            <h5>plaintext</h5>
            <pre className="pre-wrap">{opened.plaintext || '—'}</pre>
          </div>
          <div>
            <h5>marked text (delivered)</h5>
            <pre className="pre-wrap">{opened.marked_text || '—'}</pre>
          </div>
        </div>
      </section>

      {opened.marked_pdf_b64 ? (
        <section className="panel">
          <h4>The files this session produced</h4>
          <p className="note">
            Neither was downloaded for you. A file that saves itself is a file
            whose provenance is invisible, and the whole point of this screen is
            that the marked copy is tied to the ledger entry above it.
          </p>

          {opened.pdf_marked ? (
            <div className="download">
              <MarkedPdfPreview
                b64={opened.marked_pdf_b64}
                name={`${req?.doc_id || 'document'}-${req?.recipient_id || 'copy'}-marked.pdf`}
              />
              <button
                className="primary"
                onClick={() =>
                  saveBlob(
                    base64ToBlob(opened.marked_pdf_b64, 'application/pdf'),
                    `${req?.doc_id || 'document'}-${req?.recipient_id || 'copy'}-marked.pdf`,
                  )
                }
              >
                Download the marked PDF
              </button>
              <p className="note">
                A forensic copy. Its watermark is derived from ledger entry{' '}
                <strong>#{opened.ledger_entry?.index}</strong>, the one shown
                above — open this file months from now, print it, or retype a
                paragraph of it, and it still points back to that entry and to{' '}
                {req?.recipient_id || 'this recipient'}'s signature.
              </p>
              <p className="note">
                {opened.marked_pdf_pages ?? '—'} pages · sha256{' '}
                <code title={opened.marked_pdf_sha256}>
                  {shortHex(opened.marked_pdf_sha256, 20, 12)}
                </code>{' '}
                — the hash of the bytes you are about to receive, so the file can
                be checked against this page rather than taken on trust.
              </p>
            </div>
          ) : (
            <div className="result result-warn">
              <h5>no marked copy exists for this document</h5>
              <p className="note">
                This document is too short to carry a mark: its payload plan
                reports {plan.tardos_positions ?? 0} Tardos positions against{' '}
                {plan.tardos_required ?? '—'} required, so the marked text is
                identical to the plaintext. The PDF below is still yours to keep
                — it is simply not evidence of anything, and it is not labelled
                as though it were.
              </p>
            </div>
          )}

          <div className="download">
            <button
              onClick={() =>
                saveBlob(
                  base64ToBlob(opened.distribution_pdf_b64, 'application/pdf'),
                  `${req?.doc_id || 'document'}-distributed.pdf`,
                )
              }
            >
              Download the distributed PDF
            </button>
            <p className="note">
              The document as it was sealed, before any mark. This is the same
              PDF everyone who downloads the <code>.lfdoc</code> receives once
              the authority releases the key, and it attributes{' '}
              <strong>nobody</strong> — which is exactly why the marked copy has
              to be made per session instead of shipped.
            </p>
          </div>
        </section>
      ) : null}

      {opened.notes?.length ? <NotesPanel notes={opened.notes} title="server notes" /> : null}
    </>
  )
}

/**
 * The marked copy, opened inline.
 *
 * The whole distribute→open story ends in a document a recipient can actually
 * read, so the demo should end by showing one open rather than only offering a
 * download. The bytes are the same ones the button below saves -- decoded once,
 * shown in an <object>, and the object URL is revoked when this unmounts so a
 * demo that opens a dozen copies does not pin a dozen PDFs in memory.
 */
function MarkedPdfPreview({ b64, name }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)
  const lastUrl = useRef(null)

  useEffect(() => {
    setFailed(false)
    if (!b64) {
      setUrl(null)
      return undefined
    }
    let made = null
    try {
      made = URL.createObjectURL(base64ToBlob(b64, 'application/pdf'))
      lastUrl.current = made
      setUrl(made)
    } catch {
      setFailed(true)
      setUrl(null)
    }
    return () => {
      if (made) URL.revokeObjectURL(made)
    }
  }, [b64])

  if (failed) {
    return (
      <p className="note">
        the marked PDF could not be rendered inline in this browser — the
        download button below still produces the exact bytes
      </p>
    )
  }
  if (!url) return null
  return (
    <>
      <p className="note">
        The copy <strong>{name}</strong>, opened here from the same bytes the
        button below saves. This is the document a recipient keeps — every
        substituted word above is in it, and it points back to the ledger entry.
      </p>
      <object className="pdf-preview" data={url} type="application/pdf" aria-label={name}>
        <p className="note">
          inline preview unavailable — use the download button below
        </p>
      </object>
    </>
  )
}
