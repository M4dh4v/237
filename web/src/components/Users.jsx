// Tab 4: the recipient register, and the one lever that changes behaviour:
// revoke.
//
// Two things here are deliberate and worth stating rather than leaving to be
// inferred from the code.
//
// The first is that this page can only revoke. Certificates are issued by the
// CA offline -- that is a property of the design, not an omission in the UI --
// so there is no "add recipient" control here, and there should not be one
// without also changing where certificates come from.
//
// The second is what revocation is and is not. It takes effect at the next
// open: the authority checks it as step 1 of `open_document`, before any
// signature is verified and before anything is committed to the ledger. It
// cannot recall a copy somebody already opened, and it does not destroy any key
// material -- the certificate stays on file, which is why reinstating is
// possible at all. The confirmation below says both of those, because an admin
// who believes revoke un-sends a document will make a decision they would not
// otherwise make.

import { useCallback, useEffect, useState } from 'react'

import { api } from '../api.js'
import { shortHex, when } from '../format.js'

function Fingerprint({ enrolled, seen }) {
  if (!enrolled && !seen) return <span className="absent">not recorded</span>
  const differs = Boolean(enrolled && seen && enrolled !== seen)
  return (
    <>
      <code title={enrolled || ''}>{enrolled ? shortHex(enrolled, 18, 8) : '—'}</code>
      <p className="note fp-note">
        enrolled
        {seen ? (
          <>
            {' · last open asserted '}
            <code title={seen}>{shortHex(seen, 18, 8)}</code>
            {differs ? (
              <strong className="bad">
                {' '}
                — the two differ
              </strong>
            ) : null}
          </>
        ) : (
          ' · this recipient has never opened anything'
        )}
      </p>
    </>
  )
}

export default function Users({ onError, onChanged }) {
  const [rows, setRows] = useState(null)
  const [note, setNote] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [pending, setPending] = useState(null) // recipient_id awaiting confirm
  const [busy, setBusy] = useState(null) // recipient_id mid-request
  const [done, setDone] = useState(null) // { recipient_id, revoked }

  const load = useCallback(async () => {
    try {
      const body = await api.adminRecipients()
      setRows(body.recipients || [])
      setNote(body.note || null)
      setLoadError(null)
    } catch (e) {
      setLoadError(e)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function act(recipientId, revoke) {
    setBusy(recipientId)
    setPending(null)
    try {
      if (revoke) await api.revokeRecipient(recipientId)
      else await api.reinstateRecipient(recipientId)
      setDone({ recipient_id: recipientId, revoked: revoke })
      await load()
      // Whether an open succeeds just changed, so anything on another tab that
      // reported a refusal may no longer be true.
      onChanged?.()
    } catch (e) {
      onError?.(e.message)
    } finally {
      setBusy(null)
    }
  }

  if (loadError) {
    return (
      <div className="tab-body">
        <div className="panel">
          <h3>The recipient register could not be read</h3>
          <p className="note">
            {loadError.detail || loadError.message}
          </p>
          <p className="note">
            These routes are registered with the demo surface, so they exist only
            when the backend was started with a scenario attached
            (<code>scripts/demo.py --serve</code>). If <code>/demo/state</code>{' '}
            works and this does not, that is a bug rather than a missing
            deployment.
          </p>
        </div>
      </div>
    )
  }

  if (!rows) {
    return (
      <div className="tab-body">
        <div className="panel">
          <p className="note">reading the register…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="tab-body">
      <div className="panel panel-caveat">
        <h3>What revoking does, and what it cannot do</h3>
        <p className="banner-body">
          Revoking refuses the <em>next</em> open: the authority checks it before
          it verifies a signature and before it commits anything to the ledger.
          It cannot recall a copy that has already been opened, and it destroys
          no key material &mdash; the certificate stays on file, which is exactly
          why reinstating works. A revocation also survives a restart; the
          register is the authority&rsquo;s own store rather than something
          rebuilt from the deployment file.
        </p>
      </div>

      {done ? (
        <div className="result">
          <h5>
            <code>{done.recipient_id}</code>{' '}
            {done.revoked ? 'revoked' : 'reinstated'}
          </h5>
          <p className="note">
            {done.revoked
              ? 'Their next open will be refused with recipient-revoked, and no ledger entry will be written for it.'
              : 'They can open documents granted to them again, subject to every other check.'}
          </p>
        </div>
      ) : null}

      <div className="panel">
        <h3>Recipients</h3>
        <p className="note">
          Read from the authority&rsquo;s store, which is what decides whether an
          open succeeds &mdash; not from the CA&rsquo;s file, which is what the
          certificates were issued from. Where those two can be told apart, this
          is where it shows.
        </p>

        <table className="table">
          <thead>
            <tr>
              <th>recipient</th>
              <th>certificate</th>
              <th>device fingerprint</th>
              <th className="num">granted</th>
              <th className="num">opened</th>
              <th>state</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.recipient_id} className={r.revoked ? 'revoked-row' : ''}>
                <td>
                  <code>{r.recipient_id}</code>
                  <p className="note">{r.role}</p>
                </td>
                <td>
                  {r.serial ? (
                    <>
                      <code title={r.serial}>
                        {shortHex(r.serial, 12, 6)}
                      </code>
                      <p className="note">
                        issued {when(r.issued_at)} · {r.sig_alg}
                      </p>
                    </>
                  ) : (
                    <span className="absent">
                      no certificate on file
                    </span>
                  )}
                  {r.serial && !r.ca_signature_ok ? (
                    <p className="note bad">
                      the CA&rsquo;s signature does not verify — every open will
                      be refused with bad-certificate-signature
                    </p>
                  ) : null}
                </td>
                <td>
                  <Fingerprint enrolled={r.device_fp} seen={r.last_seen_device_fp} />
                </td>
                <td className="num">{r.granted}</td>
                <td className="num">{r.opened}</td>
                <td>
                  {r.revoked ? (
                    <span className="bad">revoked</span>
                  ) : (
                    <span className="present">active</span>
                  )}
                </td>
                <td>
                  {pending === r.recipient_id ? (
                    <div className="confirm">
                      <p className="note">
                        Revoke <code>{r.recipient_id}</code>? Their next open is
                        refused; a copy they already opened is not recalled.
                      </p>
                      <button
                        className="danger"
                        disabled={busy === r.recipient_id}
                        onClick={() => act(r.recipient_id, true)}
                      >
                        {busy === r.recipient_id ? 'revoking…' : 'Yes, revoke'}
                      </button>
                      <button onClick={() => setPending(null)}>Cancel</button>
                    </div>
                  ) : (
                    <button
                      className={r.revoked ? '' : 'danger'}
                      disabled={busy === r.recipient_id}
                      onClick={() =>
                        r.revoked
                          ? act(r.recipient_id, false)
                          : setPending(r.recipient_id)
                      }
                    >
                      {busy === r.recipient_id
                        ? 'working…'
                        : r.revoked
                          ? 'Reinstate'
                          : 'Revoke'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {rows.length === 0 ? (
          <p className="note">
            The authority knows no recipients. Nothing can be granted or opened
            until the deployment has issued certificates.
          </p>
        ) : null}

        {note ? (
          <div className="result result-warn">
            <h5>The device fingerprint column is a recorded claim</h5>
            <p className="note">{note}</p>
            <p className="note">
              The enrolled value comes from the deployment file; the asserted one
              arrived on the recipient&rsquo;s last request, inside the request
              their own key signed. So it is tamper-evident in the ledger &mdash;
              they cannot deny having sent that value &mdash; but they chose it,
              and no hardware was read. Treat it as corroboration, never as proof
              of which machine was used. When the two differ, that is the
              interesting case, and it is shown rather than resolved.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
