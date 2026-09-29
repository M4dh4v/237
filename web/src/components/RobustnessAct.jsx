/**
 * Act III — the real robustness numbers, and one honest limit.
 *
 * Every figure here is measured by code in the tree and asserted by a test, so
 * it cannot drift away from the claim it supports. The numbers are transcribed
 * from README.md's "Robustness" section; the honest limit at the foot is not a
 * hedge bolted on for the demo, it is the guarantee the API itself reports
 * (`ranking-only`) in every realistic case.
 */

// Rendered, degraded, OCR'd with system tesseract 5.5.3, aligned by LCS,
// decoded. Seed 7, three documents, four degradations each.
const OCR = [
  ['clean', 3, '0.0031', '0.0000'],
  ['jpeg50', 3, '0.0015', '0.0000'],
  ['resize60', 3, '0.0015', '0.0000'],
  ['combo', 3, '0.0015', '0.0000'],
  ['overall', 12, '0.0019', '0.0000'],
]

// Tardos scores, masked to the positions the extractor actually read.
// 4 users, ~1850-word documents, ~116 Tardos positions.
const TARDOS = [
  ['unmarked copy of the plaintext', 7, '0.02 – 0.24', false],
  ['fragment too short to reach the region', 8, 'no positions read', false],
  ["one recipient's marked copy, whole", 4, '1.28 – 1.70', true],
  ["one recipient's marked copy, 35% fragment", 2, '0.84 – 0.87', true],
  ['splice of two colluders', 40, '0.65 – 1.14', true],
]

export default function RobustnessAct() {
  return (
    <div className="tab-body">
      <section className="panel panel-caveat">
        <h3>What survives the attack, in measured numbers</h3>
        <p className="banner-body">
          The claim is attribution, so the number that matters is whether the
          pointer — the part of the mark that names the ledger entry — comes back
          after the copy has been through a real degradation. It did in every
          case measured.
        </p>
      </section>

      <section className="panel">
        <h4>The watermark through a real OCR pass</h4>
        <p className="note">
          Print the marked PDF, degrade it, photograph or scan it, OCR it, decode
          it. <em>Channel BER</em> is measured before any error correction, so it
          is not flattered by the coding it justifies. <em>Payload BER</em> is
          after majority voting and RS decoding.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>degradation</th>
              <th className="num">n</th>
              <th className="num">mean channel BER</th>
              <th className="num">mean payload BER</th>
            </tr>
          </thead>
          <tbody>
            {OCR.map(([deg, n, ch, pay]) => (
              <tr key={deg} className={deg === 'overall' ? 'revoked-row' : undefined}>
                <td>{deg === 'overall' ? <strong>overall</strong> : deg}</td>
                <td className="num">{n}</td>
                <td className="num">{ch}</td>
                <td className="num">{pay}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          Pointer recovered: <strong className="present">12 / 12</strong>. Payload
          BER after coding is <strong>0.0000</strong> across all twelve — the
          repetition budget sits at p = 0.008 against a measured 0.0047, so it is
          over-provisioned on purpose.
        </p>
      </section>

      <section className="panel">
        <h4>Collusion: a splice still ranks a real colluder on top</h4>
        <p className="note">
          Two recipients diff their copies to find and strip the mark. Scores are
          masked to the positions the extractor actually read.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>population</th>
              <th className="num">n</th>
              <th>top score / Z</th>
            </tr>
          </thead>
          <tbody>
            {TARDOS.map(([pop, n, score, marked]) => (
              <tr key={pop}>
                <td>{pop}</td>
                <td className="num">{n}</td>
                <td className={marked ? 'present' : 'muted'}>{score}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          Document identification (TF-IDF cosine, floor 0.25): in-corpus matches
          score 0.31 / 0.41 / 0.64; the best out-of-corpus match reaches only
          0.06 – 0.20, so an unrelated document is not misattributed.
        </p>
      </section>

      <section className="panel panel-warn">
        <h4>One honest limit — the formal Tardos bound is never met at these lengths</h4>
        <p className="note">
          The provable false-accusation guarantee holds only above a code length
          of <code>2π²c²ln(n/ε)</code> — <strong>1201 positions</strong> for 4
          users at c=2, ε=10⁻⁶. The longest document here yields 185. So a real
          colluder’s score (1.28–1.70) sits at a fraction of the threshold Z, and
          the code reports <code>guarantee: "ranking-only"</code>:
        </p>
        <p className="note">
          suspects may be <strong>ranked</strong> and their scores shown, but no
          single name is ever presented as an accusation with a stated
          false-positive rate. This is surfaced through the API status
          (<code>collusion-suspected</code>, <code>single-mark</code>), not
          buried — a document below 120 slots is <em>refused</em> rather than
          weakly marked, because a mark that cannot survive is worse than no mark
          at all.
        </p>
      </section>
    </div>
  )
}
