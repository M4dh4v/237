import { shortHex, when } from '../format.js'

/**
 * Reusable rendering for ledger material: a Signed Tree Head, its witness
 * co-signatures, a ledger entry, and the server's verification verdict.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE
 * ------------------------------------
 * The browser cannot verify any signature this system uses. The recipients,
 * the log and the witnesses all sign with ML-DSA-65 (FIPS 204); there is no
 * WebCrypto support for it, and re-implementing lattice verification in
 * JavaScript would put an unverifiable amount of unverified code between the
 * reader and the claim. So the page must never render a tick, a green word, or
 * any other affordance that reads as "checked here".
 *
 * What it can honestly report is arrival: this signature value was present in
 * the response. Hence `present` / `absent` rather than `valid` / `invalid`, and
 * hence the STANDING_NOTE that is attached to every panel below rather than
 * being printed once at the top of the page where a reader who scrolls to the
 * signatures will never see it.
 */
export const STANDING_NOTE =
  'signatures shown as received — the standalone verifier re-checks them ' +
  'out-of-band. This page cannot verify a post-quantum signature in the browser.'

/**
 * @param {object} props
 * @param {object} props.sth  signed tree head as received
 * @param {string[]} [props.witnesses]  expected witness ids, from /demo/state
 * @param {object} [props.witnessPubs]  witness id -> public key hex (display only)
 * @param {number} [props.quorum]
 * @param {string} [props.title]
 */
export function SthPanel({ sth, witnesses = [], witnessPubs = {}, quorum, title = 'Signed tree head' }) {
  if (!sth) return null
  const sigs = sth.witness_sigs || {}
  // Union of "expected" and "actually present": a signature from a witness the
  // state endpoint did not list is worth seeing, not worth hiding.
  const ids = Array.from(new Set([...witnesses, ...Object.keys(sigs)]))

  return (
    <section className="panel">
      <h4>{title}</h4>
      <p className="note">{STANDING_NOTE}</p>

      <dl className="kv">
        <dt>tree size</dt>
        <dd>{sth.tree_size}</dd>
        <dt>root hash</dt>
        <dd>
          <code title={sth.root_hash}>{shortHex(sth.root_hash, 20, 12)}</code>
        </dd>
        <dt>timestamp</dt>
        <dd>{when(sth.timestamp)}</dd>
        <dt>log signature</dt>
        <dd>
          {sth.log_sig ? (
            <code title={sth.log_sig}>{shortHex(sth.log_sig, 16, 10)}</code>
          ) : (
            <span className="absent">not present</span>
          )}
        </dd>
      </dl>

      <table className="table">
        <caption className="table-caption">
          One row per witness. "co-signed this head" means a signature value for
          this head arrived in the response — it is not a check performed here.
        </caption>
        <thead>
          <tr>
            <th>witness</th>
            <th>co-signature</th>
            <th>key on file</th>
          </tr>
        </thead>
        <tbody>
          {ids.length === 0 ? (
            <tr>
              <td colSpan={3} className="muted">
                no witnesses were reported for this head
              </td>
            </tr>
          ) : (
            ids.map((id) => {
              const sig = sigs[id]
              return (
                <tr key={id}>
                  <td>{id}</td>
                  <td>
                    {sig ? (
                      <span className="present">
                        co-signed this head{' '}
                        <code title={sig}>{shortHex(sig, 12, 8)}</code>
                      </span>
                    ) : (
                      <span className="absent">did not sign</span>
                    )}
                  </td>
                  <td>
                    {witnessPubs[id] ? (
                      <code title={witnessPubs[id]}>{shortHex(witnessPubs[id], 10, 6)}</code>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>

      {quorum != null ? (
        <p className="note">
          quorum required by this deployment: <strong>{quorum}</strong>;{' '}
          {Object.keys(sigs).length} co-signature(s) present here.
        </p>
      ) : null}
    </section>
  )
}

/** A single row's worth of ledger entry material: index, leaf hash, leaf bytes. */
export function LedgerEntryPanel({ entry, title = 'Ledger entry' }) {
  if (!entry) return null
  return (
    <section className="panel">
      <h4>{title}</h4>
      <dl className="kv">
        <dt>index</dt>
        <dd>{entry.index}</dd>
        <dt>leaf hash</dt>
        <dd>
          <code title={entry.leaf_hash}>{shortHex(entry.leaf_hash, 20, 12)}</code>
        </dd>
      </dl>
      {entry.leaf ? (
        <details className="details">
          <summary>leaf bytes as appended (the signed request, verbatim)</summary>
          <pre className="pre-wrap">{typeof entry.leaf === 'string' ? entry.leaf : JSON.stringify(entry.leaf, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  )
}

/**
 * The server's own verification verdict, rendered as a claim and not as a fact
 * established by this page.
 *
 * Wording matters here more than anywhere else in the app. `verified: true`
 * next to a green tick would read as "this browser checked the cryptography".
 * It did not; it is relaying a boolean. So every row is phrased as the
 * server's statement, and the panel leads with that framing.
 */
export function VerificationPanel({ verification }) {
  if (!verification) {
    return (
      <section className="panel">
        <h4>Verification</h4>
        <p className="note">
          no ledger entry was reached, so there is nothing to verify. This is a
          statement about the evidence, not about any person.
        </p>
      </section>
    )
  }

  const rows = [
    ['request signature (the recipient\'s)', verification.request_signature_ok],
    ['inclusion proof against the root', verification.inclusion_ok],
    ['tree head signature (the log\'s)', verification.sth_signature_ok],
    ['witness quorum', verification.witness_quorum_ok],
  ]

  return (
    <section className="panel">
      <h4>Verification</h4>
      <p className="note">
        These are the <strong>server's own statements</strong> about the checks
        it ran, relayed here. This page did not perform them and cannot. The
        check of record is <code>verifier/</code>, which re-derives all of this
        independently from the ledger's public outputs.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>check</th>
            <th>the server reports</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className={value ? 'present' : 'absent'}>
                {value === true ? 'passed' : value === false ? 'FAILED' : 'not reported'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="verify-split">
        <div>
          <h5>witnesses that co-signed</h5>
          {verification.witnesses_ok?.length ? (
            <ul className="inline-list">
              {verification.witnesses_ok.map((w) => (
                <li key={w} className="present">
                  {w}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">none reported</p>
          )}
        </div>
        <div>
          <h5>witnesses with a bad co-signature</h5>
          {verification.witnesses_bad?.length ? (
            <ul className="inline-list">
              {verification.witnesses_bad.map((w) => (
                <li key={w} className="absent">
                  {w}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">none reported</p>
          )}
        </div>
        <div>
          <h5>witnesses that did not sign</h5>
          {verification.witnesses_missing?.length ? (
            <ul className="inline-list">
              {verification.witnesses_missing.map((w) => (
                <li key={w} className="muted">
                  {w}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">none reported</p>
          )}
        </div>
      </div>

      <p className="note">
        quorum: {verification.witness_quorum ?? '—'} required ·{' '}
        {verification.verified === true
          ? 'the server reports this entry as verified'
          : 'the server does NOT report this entry as verified'}
      </p>

      {verification.notes?.length ? <NotesPanel notes={verification.notes} title="verification notes" /> : null}
    </section>
  )
}

/**
 * Server-side reasoning, collapsed by default.
 *
 * Kept in a <details> because it is the audit trail: it should be available
 * on demand and must not be summarised away, but if it is expanded by default
 * it pushes the caveat and the confidences off the first screen, and those
 * are what the reader has to see before anything else.
 */
export function NotesPanel({ notes, title = 'notes' }) {
  if (!notes?.length) return null
  return (
    <details className="details">
      <summary>
        {title} ({notes.length}) — the server's reasoning
      </summary>
      <ul className="notes">
        {notes.map((n, i) => (
          <li key={i}>{typeof n === 'string' ? n : JSON.stringify(n)}</li>
        ))}
      </ul>
    </details>
  )
}

/**
 * The list of things about this deployment that are simulated.
 *
 * Rendered on both tabs rather than on an about page. The witnesses here are
 * separate *processes* on one machine, not separate operators on separate
 * hosts, and that difference is the entire security argument for witness
 * co-signing. A reader who never sees this sentence has been misled by the
 * interface, however accurate the code underneath is.
 */
export function SimulatedPanel({ simulated }) {
  if (!simulated?.length) return null
  return (
    <section className="panel panel-simulated">
      <h4>What is simulated here</h4>
      <ul className="notes">
        {simulated.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </section>
  )
}
