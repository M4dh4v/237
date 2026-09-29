import { useRef, useState } from 'react'
import { api, ApiError, toImageDataUrl } from '../api.js'
import { pct, clamp01, when } from '../format.js'
import { VerificationPanel, NotesPanel, SimulatedPanel } from './LedgerView.jsx'

const KINDS = [
  { kind: 'text', label: 'try a text example' },
  { kind: 'screenshot', label: 'try a screenshot example' },
  { kind: 'collusion', label: 'try a collusion example' },
]

/**
 * The statuses, each with wording of its own.
 *
 * These are not tone variants of one message. A reader who has learned what
 * "no-watermark" means must not be able to confuse it with "single-mark" or
 * "unidentified" by skimming a colour, so each case names what was and was not
 * established, and the ones that could be mistaken for an accusation
 * ("single-mark" and "collusion-suspected") explicitly deny that ranking is
 * attribution. Tone only decorates the text; the text is what carries the
 * meaning.
 */
function statusCopy(result) {
  const status = result?.status
  switch (status) {
    case 'attributed':
      return {
        tone: 'attributed',
        headline: 'Attributed — the watermark decoded to a ledger entry the server reports as verified',
        // The caveat leads, deliberately. "Attributed" is the strongest word
        // this system can produce and the one most likely to be read as "this
        // person leaked it". The very first sentence after the headline has to
        // say what was actually identified.
        body:
          'What this identifies is a key, a device and a session. It does not ' +
          'identify a person: the signature proves which private key signed the ' +
          'decryption request, and nothing in the ledger records who was ' +
          'operating it.',
      }
    case 'attribution-unverified':
      return {
        tone: 'tamper',
        headline: 'Attribution unverified — a pointer decoded, but the entry it named failed verification',
        body:
          'This is the tamper case. The recovered mark pointed at a specific ' +
          'ledger entry and the checks on that entry did not hold — its ' +
          'inclusion proof, its signature, or its witness quorum. When that ' +
          'happens, no attribution is reported. A mark that names an entry the ' +
          'ledger cannot vouch for is worse than no mark at all, so this is ' +
          'reported as a failure to attribute rather than as a weak attribution.',
      }
    case 'collusion-suspected':
      return {
        tone: 'collusion',
        headline: 'Collusion suspected — the fragment carries positions from more than one session',
        body:
          'Positions in the recovered mark decode to different ledger entries, ' +
          'which is what a comparison attack looks like: two recipients diff ' +
          'their copies to find and remove the mark. The candidates below are ' +
          'ranked by collusion score. Ranking is not proof; see the guarantee ' +
          'note under the table.',
      }
    case 'single-mark':
      return {
        tone: 'collusion',
        headline: 'One mark, no pointer — a single recipient’s fingerprint is present but the entry it named did not decode',
        body:
          'This is not the same as finding nothing. One candidate’s score ' +
          'clears the accusation threshold and nobody else comes near it, ' +
          'which is the shape of one person’s mark rather than a mixture — ' +
          'and the pointer that would have named the session did not survive. ' +
          'So the candidate below is ranked, with a score, and is not an ' +
          'accusation: the ledger entry that would tie this fragment to a ' +
          'decryption was never reached.',
      }
    case 'no-watermark':
      return {
        tone: 'none',
        headline: 'The watermark did not decode, and no mark was found',
        body:
          'Nothing was recovered from this fragment and no candidate scored ' +
          'above the level noise reaches, so no ledger entry was reached and ' +
          'no attribution is possible. The sessions below are context, not a ' +
          'finding — see the framing under them before reading any name there ' +
          'as a suspect.',
      }
    case 'unidentified':
      return {
        tone: 'none',
        headline: 'Unidentified — this fragment does not match any document in the corpus',
        body:
          'Nothing was extracted, because there was nothing to extract: the ' +
          'text does not look like it came from any document the system ' +
          'distributed. This says nothing about any recipient, and no ' +
          'candidates are listed, because a list of people who scored zero on an ' +
          'unrelated document is not a result.',
      }
    case 'empty-input':
      return {
        tone: 'none',
        headline: 'Empty input — there was nothing to check',
        body: 'The request carried no text and no image. No analysis was run.',
      }
    default:
      return {
        tone: 'unknown',
        headline: `Unrecognised status: ${String(status)}`,
        body:
          'This page does not have wording for that status value. It is shown ' +
          'verbatim below rather than guessed at, because guessing what an ' +
          'unknown status means is exactly the kind of inference that would ' +
          'misattribute a document.',
      }
  }
}

export default function LeakCheck({ demoState, onError, onFailClosed }) {
  const [mode, setMode] = useState('text')
  const [text, setText] = useState('')
  const [image, setImage] = useState(null) // { dataUrl, name }
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [exampleLabel, setExampleLabel] = useState(null)
  // Held separately from `result` and rendered in its own box. The server
  // knows what it intended to plant; the checker knows what it recovered.
  // Merging them would let the expectation launder the result.
  const [pendingTruth, setPendingTruth] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [leakRecipient, setLeakRecipient] = useState('')
  const [leakKind, setLeakKind] = useState('text')
  const [generating, setGenerating] = useState(false)
  const fileInput = useRef(null)

  function reset() {
    setResult(null)
    setError(null)
    setPendingTruth(null)
    setExampleLabel(null)
  }

  async function loadExample(kind) {
    reset()
    setRunning(true)
    try {
      const data = await api.example(kind)
      if (data.kind === 'collusion' || data.leaked_text) {
        setMode('text')
        setText(data.leaked_text || '')
        setImage(null)
      }
      if (data.image_b64) {
        setMode('image')
        // The example endpoint returns a bare base64 blob, not a data: URL.
        // Normalised here because an unprefixed blob in src renders as a
        // silently broken image.
        setImage({ dataUrl: toImageDataUrl(data.image_b64), name: `${kind} example` })
        setText('')
      }
      // The example endpoints return a truth object, same shape as the ones
      // from POST /demo/leak, so the example buttons and the generate control
      // both fill the ground-truth box. It is still read defensively: a
      // deployment that serves older examples without one simply shows no box.
      if (data.truth) setPendingTruth({ source: `example: ${kind}`, truth: data.truth })
      setExampleLabel(kind)
    } catch (e) {
      setError(e)
      onError?.(e.message)
    } finally {
      setRunning(false)
    }
  }

  async function run({ textOverride } = {}) {
    reset()
    setRunning(true)
    try {
      const payload =
        mode === 'image' && image
          ? { image_b64: image.dataUrl }
          : { text: textOverride ?? text }
      const res = await api.leakcheck(payload)
      setResult(res)
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) onFailClosed?.(e.detail)
      setError(e)
      onError?.(e.message)
    } finally {
      setRunning(false)
    }
  }

  /**
   * Produce a leak from a real open, via POST /demo/leak.
   *
   * This is the only path that yields a `truth` object, and the truth is
   * stashed rather than displayed. It becomes visible only after a check has
   * run, because showing the intended answer before the check would let the
   * reader grade the result against the expectation instead of reading it.
   */
  async function generateLeak() {
    reset()
    setGenerating(true)
    try {
      const body = {
        kind: leakKind,
        recipient_id: leakRecipient || demoState?.recipients?.[0] || 'alice',
      }
      if (leakKind === 'collusion') {
        const others = (demoState?.recipients || []).filter((r) => r !== body.recipient_id)
        body.second_recipient_id = others[0] || 'bob'
      }
      const data = await api.leak(body)
      if (data.kind === 'screenshot' && data.image_b64) {
        setMode('image')
        setImage({
          dataUrl: toImageDataUrl(data.image_b64),
          name: `generated ${data.attack || 'screenshot'} leak`,
        })
        setText('')
      } else {
        setMode('text')
        setText(data.leaked_text || '')
        setImage(null)
      }
      if (data.truth) setPendingTruth({ source: `demo leak (${data.kind})`, truth: data.truth })
    } catch (e) {
      setError(e)
      onError?.(e.message)
    } finally {
      setGenerating(false)
    }
  }

  function onFile(file) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      setImage({ dataUrl: String(reader.result), name: file.name })
      setMode('image')
      setText('')
      reset()
    }
    reader.onerror = () =>
      setError(new ApiError(`could not read ${file.name} in the browser`, { kind: 'malformed' }))
    reader.readAsDataURL(file)
  }

  const canRun = mode === 'image' ? Boolean(image) : text.trim().length > 0

  return (
    <div className="tab-body">
      <section className="panel">
        <h3>What are you checking</h3>
        <p className="note">
          Paste the text or supply the image you want traced. The check runs
          entirely on the server against the ledger; this page only sends the
          fragment and renders what comes back.
        </p>

        <div className="tabs tabs-inline">
          <button className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>
            text
          </button>
          <button className={mode === 'image' ? 'active' : ''} onClick={() => setMode('image')}>
            image
          </button>
        </div>

        {mode === 'text' ? (
          <textarea
            className="textarea"
            rows={10}
            placeholder="paste the leaked fragment here"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              reset()
            }}
          />
        ) : (
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
            onClick={() => fileInput.current?.click()}
          >
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => onFile(e.target.files?.[0])}
            />
            {image ? (
              <>
                <img className="dropzone-img" src={image.dataUrl} alt={image.name} />
                <p className="note">{image.name} — click to replace</p>
              </>
            ) : (
              <p>drop a screenshot here, or click to choose a file</p>
            )}
          </div>
        )}

        <div className="row">
          <button className="primary" onClick={() => run()} disabled={running || !canRun}>
            {running ? 'checking…' : 'Run leak check'}
          </button>
          {KINDS.map((k) => (
            <button key={k.kind} onClick={() => loadExample(k.kind)} disabled={running}>
              {k.label}
            </button>
          ))}
        </div>

        <details className="details">
          <summary>
            or generate a leak from the demo session, to check end to end
          </summary>
          <p className="note">
            This runs a real open on the backend and hands you the artefact it
            produced. It is the only path here that also yields the demo's
            intended answer, which is kept hidden until a check has run.
          </p>
          <div className="row">
            <label className="field-inline">
              <span>recipient</span>
              <select
                value={leakRecipient || demoState?.recipients?.[0] || ''}
                onChange={(e) => setLeakRecipient(e.target.value)}
              >
                {(demoState?.recipients || []).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-inline">
              <span>kind</span>
              <select value={leakKind} onChange={(e) => setLeakKind(e.target.value)}>
                <option value="text">text</option>
                <option value="screenshot">screenshot</option>
                <option value="collusion">collusion (two recipients)</option>
              </select>
            </label>
            <button onClick={generateLeak} disabled={generating || running}>
              {generating ? 'generating…' : 'Generate leak'}
            </button>
          </div>
        </details>

        {running ? (
          <div className="progress">
            <div className="spinner" aria-hidden="true" />
            <div>
              <p>running the check…</p>
              {/* The stages are listed because they are what the server does,
                  but they are labelled as a description rather than animated
                  as a live trace. A progress bar that invents per-stage
                  completion would be a claim this page cannot support. */}
              <p className="note">
                the server performs all of this in one call and returns one
                result: align the fragment to a document, recover the payload
                positions, decode the pointer, look the entry up in the ledger,
                then verify that entry's proofs and witness quorum.
              </p>
            </div>
          </div>
        ) : null}

        {canRun === false && !running && !result ? (
          <p className="note">supply a fragment or pick an example to enable the check</p>
        ) : null}
      </section>

      {error ? (
        <section className="panel result-bad">
          <h4>the check did not run</h4>
          <p className="mono">{error.detail || error.message}</p>
          {error.status ? <p className="note">HTTP {error.status}</p> : null}
        </section>
      ) : null}

      {result ? (
        <>
          <StatusBanner result={result} />
          <Confidences result={result} />
          <Candidates result={result} />
          <FallbackSessions result={result} />
          <VerificationPanel verification={result.verification} />

          {result.notes?.length ? <NotesPanel notes={result.notes} title="server notes" /> : null}

          <details className="details">
            <summary>the result object as returned</summary>
            <pre className="pre-wrap">{JSON.stringify(result, null, 2)}</pre>
          </details>
        </>
      ) : null}

      {result && pendingTruth ? <GroundTruthBox pending={pendingTruth} /> : null}

      {result?.simulated?.length && !demoState?.simulated?.length ? (
        <SimulatedPanel simulated={result.simulated} />
      ) : null}
    </div>
  )
}

export function StatusBanner({ result }) {
  const copy = statusCopy(result)
  return (
    <section className={`panel banner banner-${copy.tone}`}>
      <h3>{copy.headline}</h3>
      <p className="banner-body">{copy.body}</p>
      {result.caveat ? (
        // Not truncated, not in a tooltip, not behind a disclosure: this is the
        // sentence that stops an attribution from being read as an accusation.
        <p className="caveat-text">{result.caveat}</p>
      ) : (
        <p className="note">the server returned no caveat string with this result</p>
      )}
      <p className="note">
        status code reported by the server: <code>{String(result.status)}</code>
      </p>
    </section>
  )
}

/**
 * The two confidences, side by side and structurally incapable of being
 * combined.
 *
 * These answer different questions -- "which document is this" and "did the
 * mark decode" -- and they are not two readings of one quantity. Averaging
 * them, or showing a single headline percentage, would produce a number that
 * corresponds to no property of the evidence. They are separate components
 * with their own labels for that reason, not styled into one dial.
 */
export function Confidences({ result }) {
  const doc = result.document
  const wm = result.watermark
  return (
    <section className="panel">
      <h4>Two separate confidences</h4>
      <p className="note">
        These measure different things and are never combined. There is no
        overall score.
      </p>
      <div className="confidences">
        <ConfidenceBar
          label="this text came from"
          subject={doc?.doc_id || 'no document'}
          value={doc?.confidence}
          extra={
            doc?.ambiguous ? (
              <span className="absent">
                the document match is ambiguous — more than one candidate scored close
              </span>
            ) : null
          }
          candidates={doc?.candidates}
        />
        <ConfidenceBar
          label="the mark decoded"
          subject={
            wm?.recovered ? (
              <>
                yes, to ledger index <strong>{wm.ledger_index}</strong>
              </>
            ) : (
              'no — nothing was recovered'
            )
          }
          value={wm?.confidence}
          extra={
            wm?.tardos_guarantee === 'ranking-only' ? (
              <span className="note">
                collusion positions {wm.tardos_positions} of {wm.tardos_required} required
                {' '}— ranking only
              </span>
            ) : null
          }
        />
      </div>
    </section>
  )
}

function ConfidenceBar({ label, subject, value, extra, candidates }) {
  const shown = pct(value)
  return (
    <div className="confidence">
      <div className="confidence-label">{label}</div>
      <div className="confidence-subject">{subject}</div>
      {shown === null ? (
        <div className="muted">no confidence reported</div>
      ) : (
        <>
          <div
            className="bar"
            role="img"
            aria-label={`${label}: ${shown}`}
          >
            <div className="bar-fill" style={{ width: `${clamp01(value) * 100}%` }} />
          </div>
          <div className="confidence-value">{shown}</div>
        </>
      )}
      {extra ? <div className="confidence-extra">{extra}</div> : null}
      {candidates?.length > 1 ? (
        <ul className="notes">
          {candidates.map((c) => (
            <li key={c.doc_id}>
              {c.doc_id} — {pct(c.score)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/**
 * The candidate table.
 *
 * A candidate is never rendered as a bare name. Every row carries the numbers
 * that produced it, because the whole risk of a screen like this is that a
 * reader takes a name away and drops the qualifiers. If the server supplied a
 * score, the score is on the row.
 */
export function Candidates({ result }) {
  const candidates = result.candidates || []
  const wm = result.watermark || {}
  const rankingOnly = wm.tardos_guarantee === 'ranking-only'

  // `unidentified` and `empty-input` are negatives about the evidence, not
  // about people. Printing "0 candidates" beside them would look like a
  // cleared list of suspects, which is not what was established.
  if (result.status === 'unidentified' || result.status === 'empty-input') {
    return (
      <section className="panel">
        <h4>Candidates</h4>
        <p className="note">
          none are shown, and that is not a result about anyone. With status{' '}
          <code>{result.status}</code> the check reached the conclusion that
          there was nothing here to attribute — it did not evaluate people and
          find them innocent.
        </p>
      </section>
    )
  }

  if (candidates.length === 0) {
    return (
      <section className="panel">
        <h4>Candidates</h4>
        <p className="note">
          the server returned no candidates for this fragment. No recipient is
          named, and none is implied.
        </p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h4>Candidates</h4>
      <table className="table">
        <caption className="table-caption">
          <code>ledger-pointer</code> means the watermark itself named this
          recipient's ledger entry. <code>tardos-trace</code> means the
          recipient was ranked by collusion score — a statistical ordering, not
          a pointer to an entry.
        </caption>
        <thead>
          <tr>
            <th>recipient</th>
            <th>named by</th>
            <th>collusion score</th>
            <th>threshold</th>
            <th>crosses</th>
            <th>ledger index</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c, i) => (
            <tr key={`${c.recipient_id}-${i}`}>
              <td>
                <strong>{c.recipient_id}</strong>
                {c.user_index != null ? (
                  <span className="muted"> · user index {c.user_index}</span>
                ) : null}
              </td>
              <td>
                {c.source ? (
                  <span className={c.source === 'ledger-pointer' ? 'present' : 'ranked'}>
                    {c.source}
                  </span>
                ) : (
                  <span className="muted">not reported</span>
                )}
              </td>
              <td>
                {c.tardos_score != null ? (
                  <ScoreCell score={c.tardos_score} threshold={c.tardos_threshold} />
                ) : (
                  <span className="muted">no score</span>
                )}
              </td>
              <td>{c.tardos_threshold ?? <span className="muted">—</span>}</td>
              <td
                className={
                  c.crosses_threshold === true
                    ? 'absent'
                    : c.crosses_threshold === false
                      ? 'muted'
                      : 'muted'
                }
              >
                {c.crosses_threshold === true
                  ? 'CROSSES threshold'
                  : c.crosses_threshold === false
                    ? 'does not cross'
                    : 'not reported'}
              </td>
              <td>
                {c.ledger_index != null ? (
                  c.ledger_index
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {candidates.some((c) => c.notes?.length) ? (
        <div className="candidate-notes">
          <h5>per-candidate notes</h5>
          <ul className="notes">
            {candidates.flatMap((c, i) =>
              (c.notes || []).map((n, j) => (
                <li key={`${i}-${j}`}>
                  <strong>{c.recipient_id}:</strong> {n}
                </li>
              )),
            )}
          </ul>
        </div>
      ) : null}

      {wm.tardos_guarantee ? (
        <p className={rankingOnly ? 'note note-warn' : 'note'}>
          guarantee reported by the server: <strong>{wm.tardos_guarantee}</strong>
          {rankingOnly ? (
            <>
              {' '}— the document carries {wm.tardos_positions} Tardos positions
              where the formal accusation bound needs {wm.tardos_required}. The
              scores therefore <em>rank</em> suspects; they do not support an
              accusation. A ranked list is a lead, not a finding, and a name at
              the top of this table is not a conclusion.
            </>
          ) : null}
        </p>
      ) : null}
    </section>
  )
}

/** Score with a bar filled to score/threshold, so "crosses" is visible. */
function ScoreCell({ score, threshold }) {
  const numericThreshold = typeof threshold === 'number' && threshold !== 0
  const ratio = numericThreshold ? clamp01(score / threshold) : null
  return (
    <div className="score">
      <span className="score-value">
        {typeof score === 'number' ? score.toFixed(2) : String(score)}
      </span>
      {ratio !== null ? (
        <div className="bar bar-small" role="img" aria-label={`score ${score} of threshold ${threshold}`}>
          <div
            className={score >= threshold ? 'bar-fill bar-fill-cross' : 'bar-fill bar-fill-under'}
            style={{ width: `${ratio * 100}%` }}
          />
        </div>
      ) : null}
    </div>
  )
}

/**
 * The `no-watermark` fallback: sessions listed as context.
 *
 * This panel exists because a list of recipient names is the single most
 * misreadable thing the API can return. On its own it looks like a suspect
 * list. The heading above the table says what the list actually is -- everyone
 * who decrypted this document, which includes the leaker and everyone else --
 * before any name is printed.
 */
export function FallbackSessions({ result }) {
  const sessions = result.ledger_sessions || []
  if (result.status !== 'no-watermark' || sessions.length === 0) return null

  return (
    <section className="panel panel-warn">
      <h4>These recipients decrypted this document — any of them could be the source</h4>
      <p className="note">
        This is a list of sessions that opened this document, not a ranked list
        and not an identification. Because the watermark did not decode, the
        system cannot say <em>which</em> of these copies the fragment came from.
        Every name below had legitimate access.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>ledger index</th>
            <th>recipient</th>
            <th>session time</th>
            <th>device fingerprint</th>
            <th>source address</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.ledger_index}>
              <td>{s.ledger_index}</td>
              <td>{s.recipient_id}</td>
              <td>{when(s.timestamp)}</td>
              <td>
                <code title={s.device_fp}>{s.device_fp ? String(s.device_fp).slice(0, 16) : '—'}</code>
              </td>
              <td>{s.source_ip || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/**
 * The demo's own ground truth, in a box of its own.
 *
 * Kept out of the result rendering entirely -- not as a footnote to it, not
 * interleaved with it -- because it is not evidence. It is what the script
 * intended to plant, and if it sits inside the result panel a reader will take
 * the expectation as confirmation of the finding. It is only shown after a
 * check has run, so it cannot prime the reader before they see the result.
 */
function GroundTruthBox({ pending }) {
  return (
    <section className="panel panel-truth">
      <h4>Demo ground truth — not part of the result</h4>
      <p className="note">
        This is what the demo script intended to plant ({pending.source}). It is
        not evidence and it was not produced by the check. It is shown here,
        separately, so the recovered result above can be compared against the
        expectation rather than quietly substituted by it.
      </p>
      <pre className="pre-wrap">{JSON.stringify(pending.truth, null, 2)}</pre>
    </section>
  )
}
