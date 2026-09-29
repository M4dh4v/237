/**
 * Fail-closed as a demonstrated guarantee, NOT an error (design plan §12.2,
 * sakshya-honesty §2). Green-framed and calm: the key was withheld because the
 * record could not be committed. Never a red box.
 *
 * `reason` accepts an ApiError (reads its .detail/.message) or a plain string.
 *
 * STUB: props frozen. Detection (api.isFailClosed) stays in the dashboards.
 */
export default function FailClosed({ reason }) {
  const detail =
    (reason && typeof reason === 'object' && (reason.detail || reason.message)) ||
    (typeof reason === 'string' ? reason : null)

  return (
    <div
      role="note"
      style={{
        border: '1px solid var(--verified)',
        borderRadius: 'var(--radius)',
        background: 'var(--bg-panel)',
        padding: 'calc(var(--gap) * 1.25)',
        maxWidth: 560,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          color: 'var(--verified)',
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        <span aria-hidden style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--verified)' }} />
        Fail-closed — guarantee held
      </div>
      <p style={{ margin: 0, color: 'var(--ink)' }}>
        The system refused to release the key because it could not write the record.
      </p>
      {detail ? (
        <p style={{ margin: '8px 0 0', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-muted)' }}>
          {detail}
        </p>
      ) : null}
    </div>
  )
}
