/**
 * Act II — tamper.
 *
 * The video beat is one sentence: "edit a block, the alarm fires, and the other
 * nodes still verify." This panel presents exactly that, and is careful about
 * one thing: the tamper it describes is a *real* destructive UPDATE against the
 * ledger's own SQLite file, which is why it is run out-of-band by
 * `make tamper` on a throwaway deployment rather than fired against the live
 * demo ledger the rest of this page is reading from. Corrupting that ledger
 * mid-demo would break every panel above, and a demo that has to lie about the
 * state of its own store to show tamper-evidence is not showing tamper-evidence.
 *
 * So this act shows what that run produces: the same four verification checks
 * the audience just watched pass in Act I, now failing, and the escalation of
 * six attacks with what catches each. Nothing here is a mock of a check — the
 * check of record is `verifier/`, and the numbers and refusals are the ones
 * `scripts/tamper_demo.py` prints.
 */

// The four checks, mirrored from LedgerView's VerificationPanel so the audience
// sees the identical row set they saw pass, now with the verdict flipped.
const CHECKS_AFTER_TAMPER = [
  ["request signature (the recipient's)", 'passed', 'The signature is still valid — the attacker did not forge it, they edited the entry around it. Validity of the signature is not integrity of the log.'],
  ['inclusion proof against the root', 'FAILED', 'The edited entry no longer folds to the root the witnesses co-signed. This is the alarm.'],
  ["tree head signature (the log's)", 'passed', 'In this build the log key sits in the same file as the ledger, so an operator can re-sign a rebuilt head. It does not help — see attack 2.'],
  ['witness quorum', 'FAILED', 'A witness will not co-sign a second, different root at a size it has already signed. The other nodes still verify against their own state.'],
]

// The six attacks, in increasing order of how much has to be subverted, from
// scripts/tamper_demo.py. Attack 1 is the "edit a block" beat; 3–5 are "the
// other nodes still verify"; 6 is the independent auditor.
const ATTACKS = [
  ['Rewrite a committed entry.', 'The entry no longer folds to the root the witnesses signed.'],
  ['Rewrite it, rebuild the tree, and re-sign the head with the log’s own key.', 'The rebuilt head is not a consistent extension of the root already externalized. The attacker holds every key the server holds and it still does not help.'],
  ['Ask a witness to co-sign the rebuilt root at the same size.', 'It already signed a different root at that size. Equivocation — refused.'],
  ['Ask a witness to co-sign an altered head at a size below its high-water mark.', 'It will not sign a size behind its high-water mark, even one it has no record of signing.'],
  ['Ask a witness to co-sign a larger head with no usable proof.', 'It verifies the extension against its own last root rather than trusting that a proof was supplied.'],
  ['Hand the result to the standalone verifier.', 'The verifier reports the witness disagreement and the anchor contradiction, by name — sharing no code with the server.'],
]

export default function TamperAct() {
  return (
    <div className="tab-body">
      <section className="panel panel-caveat">
        <h3>Edit a committed block. The alarm fires; the other nodes still verify.</h3>
        <p className="banner-body">
          The tamper below is a real <code>UPDATE</code> against the ledger’s own
          SQLite file — not a mock. It is run by <code>make tamper</code> on a
          throwaway deployment rather than against the live ledger this page is
          reading, because corrupting that store to prove a point would break
          every panel in Act I. What follows is what that run produces.
        </p>
      </section>

      <section className="panel banner banner-tamper">
        <h3>The same four checks from Act I — now, on the edited entry</h3>
        <p className="note">
          These are the exact rows the audience watched pass under the marked
          copy. On a tampered entry, two of them flip. Colour is a second
          channel; the verdict is the word.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>check</th>
              <th>verdict</th>
              <th>why</th>
            </tr>
          </thead>
          <tbody>
            {CHECKS_AFTER_TAMPER.map(([label, verdict, why]) => (
              <tr key={label}>
                <td>{label}</td>
                <td className={verdict === 'passed' ? 'present' : 'absent'}>{verdict}</td>
                <td className="note" style={{ margin: 0 }}>{why}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          The two failures are independent: the inclusion proof breaks because
          the leaf changed, and the quorum breaks because the witnesses refuse to
          endorse the rewrite. An attacker would have to defeat both, plus the
          externalized anchor, plus the standalone verifier below.
        </p>
      </section>

      <section className="panel">
        <h4>Six attacks, in order of how much of the system must be subverted</h4>
        <p className="note">
          Attack 1 is what a plain hash chain catches. Attacks 2–5 are what the
          witnesses and the externalized anchor exist for. Attack 6 is the
          auditor who trusts none of it. Every refusal here is the wording the
          witness and verifier actually emit.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>attack</th>
              <th>caught by</th>
            </tr>
          </thead>
          <tbody>
            {ATTACKS.map(([attack, caught], i) => (
              <tr key={i}>
                <td className="num">{i + 1}</td>
                <td>{attack}</td>
                <td className="present">{caught}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel panel-simulated">
        <h4>To run it live</h4>
        <p className="note">
          <code>make tamper</code> builds a fresh ledger, commits real entries,
          then performs each attack above against the running witness processes
          and finishes with <code>python -m verifier.verify</code> — a checker
          that imports nothing from the server. The escalation and every refusal
          string printed there are the source for this panel.
        </p>
      </section>
    </div>
  )
}
