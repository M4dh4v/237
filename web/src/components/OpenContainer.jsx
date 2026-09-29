// Tab 3: open a .lfdoc that someone handed you.
//
// The page exists to make one sentence concrete: **this file cannot be read
// here.** It holds the document encrypted under a content key that is itself
// wrapped to the *authority's* ML-KEM public key, and no private key ever
// reaches a browser. So the page does the three things that are actually
// available to it, in order, and is careful to say which is which:
//
//   1. Read the header locally, holding no key. That is a *label* -- the AEAD
//      binds only the doc_id, so every other field is editable by anyone
//      holding the file.
//   2. Check the file against the authority's copy of the same document id,
//      by hashing both in the browser. This step is why the page can be
//      trusted to open the right thing at all: the open is performed by the
//      authority on *its* document, chosen by a doc_id out of a header that is
//      not authenticated. Without this check a doctored label would get you a
//      PDF from a different document, and nothing on screen would say so.
//      The open button stays disabled until this check has matched.
//   3. Open it, and only then compare the label with the manifest that
//      travelled *inside* the encryption. Before the open the label was a
//      claim; after it, it is checkable, and a disagreement is the finding:
//      somebody edited the envelope.
//
// What is deliberately absent: any pretence of reading the ciphertext, and any
// inline preview of the container. The preview here is of the *opened* copy,
// rendered from the marking this session's ledger entry produced, and it is
// labelled with that entry.

import { useCallback, useEffect, useRef, useState } from 'react'

import { api, isFailClosed } from '../api.js'
import {
  compareLabels,
  ContainerError,
  parseContainer,
  sha256Hex,
} from '../container.js'
import { base64ToBlob } from '../download.js'
import { shortHex, when } from '../format.js'
import { OpenResult } from './DistributeOpen.jsx'

/**
 * An object URL for base64 file content, revoked when it changes or unmounts.
 *
 * A blob URL pins its bytes for the lifetime of the document, and the opened
 * copy is the largest thing this page handles, so the revoke is not tidiness --
 * but it is deferred to the next tick, because revoking a URL the browser is
 * still opening in a viewer shows a broken document.
 */
function useBlobUrl(b64, type) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    if (!b64) {
      setUrl(null)
      return undefined
    }
    const objectUrl = URL.createObjectURL(base64ToBlob(b64, type))
    setUrl(objectUrl)
    return () => setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  }, [b64, type])
  return url
}

function SectionTable({ sections }) {
  if (!Array.isArray(sections) || sections.length === 0) return null
  return (
    <table className="table">
      <caption className="table-caption">
        What is inside the encrypted part, described without revealing any of it.
        The names and lengths are the one thing the header leaks: they give the
        approximate size of the text and of the PDF.
      </caption>
      <thead>
        <tr>
          <th>section</th>
          <th>bytes</th>
          <th>sha256 of the plaintext</th>
        </tr>
      </thead>
      <tbody>
        {sections.map((s) => (
          <tr key={s.name}>
            <td>
              <code>{s.name}</code>
            </td>
            <td className="mono">{s.length}</td>
            <td>
              <code title={s.sha256}>{shortHex(s.sha256, 20, 10)}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function OpenContainer({
  demoState,
  onError,
  onFailClosed,
  onOpenSucceeded,
  onSessionChanged,
}) {
  const recipients = demoState?.recipients || []

  const [documents, setDocuments] = useState([])
  const [pickDocId, setPickDocId] = useState('')
  const [pickBusy, setPickBusy] = useState(false)

  const [entry, setEntry] = useState(null) // { name, buffer, parsed, size }
  const [fileError, setFileError] = useState(null)
  const [origin, setOrigin] = useState(null) // 'file' | 'authority'
  const [dragging, setDragging] = useState(false)

  const [check, setCheck] = useState(null) // { state, mine, theirs, detail }
  const [recipient, setRecipient] = useState(null)
  const [opening, setOpening] = useState(false)
  const [opened, setOpened] = useState(null)
  const [openError, setOpenError] = useState(null)
  const [refused, setRefused] = useState(null)

  const inputRef = useRef(null)

  useEffect(() => {
    let live = true
    api
      .documents()
      .then((d) => {
        if (!live) return
        const sealed = (d.documents || []).filter((doc) => doc.sealed)
        setDocuments(sealed)
        setPickDocId((cur) => cur || sealed[0]?.doc_id || '')
      })
      .catch((e) => onError?.(e.message))
    return () => {
      live = false
    }
  }, [onError])

  const header = entry?.parsed?.header
  const docId = typeof header?.doc_id === 'string' ? header.doc_id : null

  const adopt = useCallback((buffer, name, from) => {
    // Every downstream fact belongs to the previous file, so all of it goes.
    setOpened(null)
    setOpenError(null)
    setRefused(null)
    setCheck(null)
    setOrigin(from)
    let parsed = null
    try {
      parsed = parseContainer(buffer)
      setFileError(null)
    } catch (e) {
      setFileError(e)
    }
    setEntry({ name, buffer, parsed, size: buffer.byteLength })
    return parsed
  }, [])

  function onFile(file) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => adopt(reader.result, file.name, 'file')
    reader.onerror = () =>
      setFileError(
        new ContainerError(`could not read ${file.name} in the browser`),
      )
    // readAsArrayBuffer rather than the data-URL read the screenshot dropzone
    // uses: this is a binary format and the bytes are hashed below, so a
    // base64 round trip in the middle would be a chance to change them.
    reader.readAsArrayBuffer(file)
  }

  const verify = useCallback(
    async (target) => {
      const id = target?.parsed?.header?.doc_id
      if (typeof id !== 'string' || !id) {
        setCheck({
          state: 'error',
          detail: 'this header carries no doc_id, so there is nothing to look up',
        })
        return
      }
      setCheck({ state: 'checking' })
      try {
        const [mine, theirs] = await Promise.all([
          sha256Hex(target.buffer),
          api.containerBytes(id).then((b) => sha256Hex(b)),
        ])
        setCheck(
          mine === theirs
            ? { state: 'match', mine, theirs }
            : { state: 'mismatch', mine, theirs },
        )
      } catch (e) {
        if (e.status === 404) {
          setCheck({
            state: 'missing',
            detail:
              `the authority holds no document ${id}. This file may be from a ` +
              `different deployment, or its label may have been edited.`,
          })
        } else {
          setCheck({ state: 'error', detail: e.message })
        }
      }
    },
    [],
  )

  async function loadFromAuthority(id) {
    if (!id) return
    setPickBusy(true)
    try {
      const buffer = await api.containerBytes(id)
      const parsed = adopt(buffer, `${id}.lfdoc`, 'authority')
      // Fetched from the authority, so the comparison below is true by
      // construction. It is run anyway: one code path, and the reader still
      // sees the value both sides hashed.
      if (parsed) await verify({ buffer, parsed })
    } catch (e) {
      onError?.(e.message)
    } finally {
      setPickBusy(false)
    }
  }

  async function doOpen() {
    setOpening(true)
    setOpened(null)
    setOpenError(null)
    setRefused(null)
    try {
      const res = await api.open({
        doc_id: docId,
        recipient_id: recipient,
        mark: true,
        include_pdf: true,
      })
      setOpened(res)
      onSessionChanged?.()
      onOpenSucceeded?.()
    } catch (e) {
      if (isFailClosed(e)) {
        // The guarantee firing, not an error path. Same treatment as tab 1.
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

  const markedUrl = useBlobUrl(opened?.marked_pdf_b64, 'application/pdf')
  const disagreements = opened
    ? compareLabels(header, opened.payload_manifest)
    : null
  const canOpen = check?.state === 'match' && Boolean(recipient) && !opening

  return (
    <div className="tab-body">
      <div className="panel panel-caveat">
        <h3>This page cannot read the file you are about to give it</h3>
        <p className="banner-body">
          A <code>.lfdoc</code> carries the document encrypted under a content
          key, and carries that key wrapped to the <em>authority&rsquo;s</em>{' '}
          ML-KEM public key. Only the authority can unwrap it, and no such key
          exists in this browser. So anything read here <em>locally</em> is the
          file&rsquo;s own description of itself, and the content arrives only
          after the authority releases a key &mdash; which it will not do until
          the recipient&rsquo;s signature is committed to the ledger. That is the
          point of the system, not a limitation of this page.
        </p>
      </div>

      <div className="panel">
        <h3>Give it a file</h3>
        <div
          className={dragging ? 'dropzone dragging' : 'dropzone'}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            onFile(e.dataTransfer.files?.[0])
          }}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".lfdoc,application/octet-stream"
            hidden
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          {entry ? (
            <p className="note">
              <code>{entry.name}</code> &mdash; {entry.size.toLocaleString()}{' '}
              bytes, read from{' '}
              {origin === 'authority'
                ? 'the authority itself'
                : 'a file on this machine'}
              . Click to replace.
            </p>
          ) : (
            <p>drop a .lfdoc here, or click to choose one</p>
          )}
        </div>

        {documents.length ? (
          <div className="row">
            <span className="field-label">
              or open one this deployment already holds
            </span>
            <select
              value={pickDocId}
              onChange={(e) => setPickDocId(e.target.value)}
            >
              {documents.map((d) => (
                <option key={d.doc_id} value={d.doc_id}>
                  {d.doc_id} &mdash; {d.classification}
                </option>
              ))}
            </select>
            <button
              onClick={() => loadFromAuthority(pickDocId)}
              disabled={pickBusy}
            >
              {pickBusy ? 'fetching…' : 'Fetch it'}
            </button>
            <p className="note preview">
              Fetched from the authority, so the comparison in step 2 is true by
              construction. It is here so the page can be driven without first
              downloading a file &mdash; the check below earns its keep on a file
              you were handed.
            </p>
          </div>
        ) : null}

        {fileError ? (
          <div className="result result-bad">
            <h5>This is not a container this page can read</h5>
            <p className="note">{fileError.message}</p>
            <p className="note">
              Nothing was sent anywhere and nothing was opened. A file that fails
              here is either not a <code>.lfdoc</code> at all, or was truncated in
              transit &mdash; the header length is checked against the file rather
              than trusted, so a half-downloaded file says so instead of looking
              like a bad key.
            </p>
          </div>
        ) : null}
      </div>

      {header ? (
        <>
          <div className="panel">
            <h3>1 · What this file says about itself</h3>
            <p className="note">
              Read in this browser from the header, with no key and no request to
              the server.
            </p>
            <dl className="kv">
              <dt>doc id</dt>
              <dd>
                <code>{header.doc_id}</code>
              </dd>
              <dt>classification</dt>
              <dd>{header.classification ?? '—'}</dd>
              <dt>cipher</dt>
              <dd>
                {header.cipher ?? '—'} {header.kem_alg ? `· ${header.kem_alg}` : ''}
              </dd>
              <dt>container</dt>
              <dd>
                {header.container ?? '—'} v{header.container_version ?? '?'} ·
                frame {header.frame ?? '—'}
              </dd>
              <dt>created</dt>
              <dd>{when(header.created)}</dd>
              <dt>font · pages</dt>
              <dd>
                {header.font ?? '—'} · {header.pages ?? '—'}
              </dd>
              <dt>doc sha256</dt>
              <dd>
                <code title={header.doc_hash}>
                  {shortHex(header.doc_hash, 20, 10)}
                </code>{' '}
                <span className="muted">(of the canonical text)</span>
              </dd>
              <dt>pdf sha256</dt>
              <dd>
                <code title={header.pdf_hash}>
                  {shortHex(header.pdf_hash, 20, 10)}
                </code>{' '}
                <span className="muted">(of the PDF sealed at distribution)</span>
              </dd>
              <dt>manifest sha256</dt>
              <dd>
                <code title={header.manifest_sha256}>
                  {shortHex(header.manifest_sha256, 20, 10)}
                </code>
              </dd>
              <dt>ciphertext</dt>
              <dd className="mono">
                {entry.parsed.ciphertextBytes.toLocaleString()} bytes
              </dd>
              <dt>key envelope</dt>
              <dd>
                <span className="present">present</span> —{' '}
                <code title={header.key_envelope}>
                  {shortHex(header.key_envelope || '', 20, 10)}
                </code>
                <p className="note">
                  The content key, wrapped to the authority&rsquo;s public key.
                  Publishing it is deliberate: anyone may hold it and only the
                  authority can unwrap it. It is what makes this file a complete
                  description of itself and useless on its own.
                </p>
              </dd>
            </dl>

            <SectionTable sections={header.sections} />

            <div className="result result-warn">
              <h5>This label is not authenticated</h5>
              <p className="note">
                The encryption here binds only the <code>doc_id</code>. Every
                other field above &mdash; the classification, the page count, the
                hashes, the date &mdash; can be rewritten by anyone holding this
                file, and the file will still decrypt. So this panel is what the
                file <em>claims</em>. Step 2 is the first check that costs
                anything, and step 3 is the first one that can actually
                authenticate the label.
              </p>
            </div>
          </div>

          <div className="panel">
            <h3>2 · Is this the file the authority holds?</h3>
            <p className="note">
              The open in step 3 is performed by the authority on <em>its</em>{' '}
              copy of <code>{docId ?? '…'}</code>, chosen by a doc id out of the
              label above. So this comparison is what stands between an edited
              label and a document you were never sent: both files are hashed
              here, in the browser, and the open stays disabled until they match.
            </p>
            <div className="row">
              <button onClick={() => verify(entry)} disabled={!entry?.parsed}>
                {check?.state === 'checking'
                  ? 'hashing both…'
                  : 'Check against the authority'}
              </button>
            </div>

            {check?.state === 'match' ? (
              <div className="result">
                <h5>This is the container the authority holds for that id</h5>
                <p className="note">
                  Both files hash to the same value. The label&rsquo;s{' '}
                  <code>doc_id</code> therefore points at the document whose
                  ciphertext is in your hand &mdash; which is what makes opening
                  it meaningful.
                </p>
                <p className="note mono">{check.mine}</p>
              </div>
            ) : null}

            {check?.state === 'mismatch' ? (
              <div className="result result-bad">
                <h5 className="bad">
                  This is not the file the authority holds
                </h5>
                <p className="note">
                  The authority&rsquo;s copy of{' '}
                  <code>{docId}</code> is a different file. Opening by that id
                  would release a key for <em>its</em> document and hand you a
                  PDF that has nothing to do with the bytes you were given
                  &mdash; so the open is refused here.
                </p>
                <p className="note">
                  Two ordinary explanations, and one that is not: the file predates
                  a re-distribution of that document, or it came from a different
                  deployment &mdash; or its label was edited to point at another
                  document. There is nothing on this page that can tell those
                  apart.
                </p>
                <dl className="kv">
                  <dt>your file</dt>
                  <dd className="mono">{check.mine}</dd>
                  <dt>the authority&rsquo;s</dt>
                  <dd className="mono">{check.theirs}</dd>
                </dl>
              </div>
            ) : null}

            {check?.state === 'missing' ? (
              <div className="result result-warn">
                <h5>No such document at the authority</h5>
                <p className="note">{check.detail}</p>
              </div>
            ) : null}

            {check?.state === 'error' ? (
              <div className="result result-bad">
                <h5>Could not run the check</h5>
                <p className="note">{check.detail}</p>
                <p className="note">
                  The open is disabled rather than offered unchecked: without this
                  comparison there is nothing tying the document the authority
                  would open to the file in front of you.
                </p>
              </div>
            ) : null}
          </div>

          <div className="panel">
            <h3>3 · Open it</h3>
            <p className="note">
              This appends a ledger entry and only then releases a one-time key
              &mdash; the ordering the whole system exists for. Choose the
              identity to open as; the authority refuses anyone not granted this
              document, which is default-deny rather than a malfunction.
            </p>

            <div className="row">
              <span className="field-label">open as</span>
              {recipients.length ? (
                <select
                  value={recipient ?? ''}
                  onChange={(e) => setRecipient(e.target.value || null)}
                >
                  <option value="">— choose a recipient —</option>
                  {recipients.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="note">
                  this deployment lists no recipients; the backend may not have a
                  scenario attached
                </span>
              )}
              <button className="primary" onClick={doOpen} disabled={!canOpen}>
                {opening ? 'opening…' : 'Open the document'}
              </button>
            </div>

            {check?.state !== 'match' ? (
              <p className="note note-warn">
                Disabled until step 2 has matched. An open sends the doc id from
                the label to the authority; without the comparison there is
                nothing saying that id names the document you are holding.
              </p>
            ) : null}

            {refused ? (
              <div className="result result-refused">
                <h5>REFUSED: the ledger could not be extended, so no key was released</h5>
                <p className="note">{refused}</p>
                <p className="note">
                  This is fail-closed working. The authority had already verified
                  the request; it stopped because it could not commit the entry
                  that would record the open, and an open that is not recorded is
                  not allowed to happen.
                </p>
              </div>
            ) : null}

            {openError ? (
              <div className="result result-bad">
                <h5>The authority refused this open</h5>
                <p className="note">
                  {openError.detail || openError.message}
                </p>
                <p className="note">
                  No ledger entry was written and no key was produced, so there is
                  nothing recorded that did not happen.
                </p>
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {opened ? (
        <>
          <div className="panel">
            <h3>4 · The label, against the manifest that travelled inside</h3>
            {disagreements && disagreements.length === 0 ? (
              <div className="result">
                <h5>The label agrees with the sealed manifest</h5>
                <p className="note">
                  This is the first check on this page that can actually
                  authenticate the header. The manifest came out of the
                  decryption, so it is covered by the same AEAD as the document;
                  the label was not. Field for field, they match.
                </p>
              </div>
            ) : (
              <div className="result result-bad">
                <h5 className="bad">
                  The label disagrees with what was sealed
                </h5>
                <p className="note">
                  These fields differ between the header and the authenticated
                  manifest: {disagreements.join(', ')}.
                </p>
                <p className="note">
                  The manifest is the one to believe &mdash; it travelled inside
                  the encryption. The disagreement is the finding: somebody
                  edited the label on the outside of the envelope.
                </p>
              </div>
            )}
          </div>

          <OpenResult
            opened={opened}
            witnesses={demoState?.witnesses}
            witnessPubs={demoState?.witness_pubs}
            quorum={demoState?.min_witnesses}
            startAt={5}
          />

          {markedUrl ? (
            <div className="panel">
              <h3>The opened copy</h3>
              <p className="note">
                This is the <em>marked</em> copy, rendered from the substitutions
                this session&rsquo;s ledger entry produced &mdash; not the sealed
                container, which no viewer can open. The mark is derived from the
                leaf hash above, so this file points back at that entry even after
                it is printed, photographed or retyped.
              </p>
              <object
                className="pdf-preview"
                data={markedUrl}
                type="application/pdf"
                aria-label="the opened, marked copy of the document"
              >
                <p className="note">
                  This browser will not display a PDF inline. The download
                  button above gives you the same bytes.
                </p>
              </object>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
