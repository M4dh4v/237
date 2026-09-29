import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { parseLeaf, shortHex, when } from '../format.js'

// Cytoscape is heavy and only this view needs it, so the canvas is split out and
// loaded on demand -- the rest of the flow does not pay for it.
const ChainGraph = lazy(() =>
  import('./ChainGraph.jsx').then((m) => ({ default: m.ChainGraph })),
)

/**
 * The ledger, as a graph, driven entirely by data this system already serves.
 *
 * There is no /ledger/graph endpoint here (new237 had one); this builds the
 * Cytoscape elements in the browser from /ledger/entries plus the head that
 * /demo/state already polls. That keeps one honest property: the graph cannot
 * show a leaf the entries list does not contain, and it cannot invent a quorum
 * the head does not report.
 *
 * The one verdict on the canvas -- green vs red -- is the head's, not each
 * leaf's. In a Merkle log every committed leaf is included under the single
 * signed tree head, so the meaningful question is whether THAT head carries a
 * witness quorum. See ChainGraph's header for why the per-leaf framing of the
 * blockchain version does not transfer.
 */
export default function LedgerGraph({ demoState, onError }) {
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  const sth = demoState?.sth
  const treeSize = sth?.tree_size ?? 0
  const quorum = demoState?.min_witnesses ?? null
  const sigCount = sth?.witness_sigs ? Object.keys(sth.witness_sigs).length : 0
  // The single judgement, made once and applied to the whole tree.
  const quorumOk = quorum != null && sigCount >= quorum

  // Re-fetch when the tree grows (opening a document appends a leaf). Fetching
  // ascending gives 0..N-1 in the order the graph draws them.
  useEffect(() => {
    let live = true
    if (treeSize === 0) {
      setEntries([])
      return () => {
        live = false
      }
    }
    api
      .ledgerEntries(200, 'asc')
      .then((res) => {
        if (!live) return
        setEntries(res.entries || [])
        setError(null)
      })
      .catch((e) => {
        if (!live) return
        setError(e.message)
        onError?.(e.message)
      })
    return () => {
      live = false
    }
  }, [treeSize, onError])

  const elements = useMemo(() => {
    if (!entries || entries.length === 0) return []
    const tone = quorumOk ? 'q' : 'x'
    const els = []
    for (const e of entries) {
      els.push({ data: { id: `n${e.index}`, index: e.index, label: `#${e.index}`, tone } })
      if (e.index > 0) {
        // "appended after": the arrow points from the newer leaf to the one
        // before it.
        els.push({ data: { source: `n${e.index}`, target: `n${e.index - 1}` } })
      }
    }
    const last = entries[entries.length - 1]
    els.push({ data: { id: 'head', head: true, tone, label: `STH ${treeSize}` } })
    els.push({ data: { source: 'head', target: `n${last.index}` } })
    return els
  }, [entries, quorumOk, treeSize])

  const selectedEntry = useMemo(() => {
    if (selected == null || !entries) return null
    return entries.find((e) => e.index === selected) || null
  }, [selected, entries])

  if (!sth) {
    return <p className="note muted">no signed tree head has been reported yet — open a document to append the first leaf.</p>
  }
  if (error) {
    return <p className="note absent">could not load ledger entries: {error}</p>
  }
  if (entries === null) {
    return <p className="note muted">loading ledger entries…</p>
  }
  if (entries.length === 0) {
    return <p className="note muted">the ledger has no entries yet.</p>
  }

  return (
    <div>
      <p className="note">
        One node per committed leaf, oldest at the root, each appended after the
        one before it; the diamond is the current signed tree head. The colour is
        the head's single verdict: <strong>{sigCount}</strong> witness
        co-signature(s) present against a quorum of{' '}
        <strong>{quorum ?? '—'}</strong>, so the head{' '}
        {quorumOk ? (
          <span className="present">carries quorum</span>
        ) : (
          <span className="absent">does not carry quorum</span>
        )}
        . Tap a leaf to read what was appended.
      </p>

      <Suspense fallback={<p className="note muted">loading the graph…</p>}>
        <ChainGraph elements={elements} onSelect={setSelected} selected={selected} />
      </Suspense>

      {selectedEntry ? <SelectedLeaf entry={selectedEntry} /> : null}
    </div>
  )
}

/** What a tapped leaf actually is: its hash, and the request that was appended. */
function SelectedLeaf({ entry }) {
  const { parsed, raw, error } = parseLeaf(entry.leaf)
  // The signed request sits under `request`; `kind` and `source_ip` wrap it.
  const req = parsed?.request ?? parsed ?? {}
  const docId = req.doc_id ?? req.document_id ?? null
  const recipient = req.recipient_id ?? req.recipient ?? null
  const ts = req.timestamp ?? parsed?.timestamp ?? null

  return (
    <section className="panel">
      <h4>Leaf #{entry.index}</h4>
      <dl className="kv">
        <dt>leaf hash</dt>
        <dd>
          <code title={entry.leaf_hash}>{shortHex(entry.leaf_hash, 20, 12)}</code>
        </dd>
        {docId ? (
          <>
            <dt>document</dt>
            <dd>
              <code>{docId}</code>
            </dd>
          </>
        ) : null}
        {recipient ? (
          <>
            <dt>recipient</dt>
            <dd>
              <code>{recipient}</code>
            </dd>
          </>
        ) : null}
        {parsed?.kind ? (
          <>
            <dt>kind</dt>
            <dd>
              <code>{parsed.kind}</code>
            </dd>
          </>
        ) : null}
        {ts ? (
          <>
            <dt>appended</dt>
            <dd>{when(ts)}</dd>
          </>
        ) : null}
      </dl>
      <details className="details">
        <summary>leaf bytes as appended (the signed request, verbatim)</summary>
        {error ? <p className="note absent">{error}</p> : null}
        <pre className="pre-wrap">{raw ?? JSON.stringify(parsed, null, 2)}</pre>
      </details>
    </section>
  )
}
