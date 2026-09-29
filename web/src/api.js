// The single place the app talks to the backend.
//
// Every function here throws an ApiError. Nothing returns null-on-failure,
// because a null is indistinguishable from "the server said nothing useful"
// and the UI then has no choice but to render a blank panel. A thrown error
// carrying a specific, human-readable message is the only shape that lets
// each screen say what actually went wrong -- and "the backend is not running"
// is the single most likely thing to go wrong when someone opens this app.

import { filenameFromDisposition } from './download.js'

export const BACKEND_HINT =
  'the demo backend is not reachable on 127.0.0.1:8443 — start it with ' +
  '`python scripts/demo.py --serve`'

export class ApiError extends Error {
  /**
   * @param {string} message  shown verbatim in the UI
   * @param {object} info
   * @param {'unreachable'|'http'|'malformed'} info.kind
   * @param {number} [info.status]
   * @param {string} [info.detail]  the server's own `detail` string, if any
   * @param {string} [info.url]
   */
  constructor(message, { kind, status, detail, url } = {}) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind || 'malformed'
    this.status = status
    this.detail = detail
    this.url = url
  }
}

/** True when the failure is "nothing is listening", which gets its own screen. */
export function isUnreachable(err) {
  return err instanceof ApiError && err.kind === 'unreachable'
}

/**
 * A 503 is not an error condition to be apologised for. It is the fail-closed
 * guarantee firing: the ledger could not be extended, so no key was released.
 * The caller distinguishes it so it can be presented as a demonstrated
 * outcome rather than a red box.
 *
 * Detection is by substring, not by prefix, and that is not sloppiness. The
 * two routes word this differently: the real POST /open raises
 * `HTTPException(503, f"fail-closed: {e}")`, but POST /demo/open wraps the
 * client's OpenRefused, whose message is
 * `authority returned 503: {"detail":"fail-closed: ..."}`. Matching only the
 * prefix would silently drop the demo route's 503 back into the generic error
 * path -- which is exactly the case the UI is supposed to showcase.
 */
export function isFailClosed(err) {
  return (
    err instanceof ApiError &&
    err.status === 503 &&
    typeof err.detail === 'string' &&
    err.detail.includes('fail-closed')
  )
}

/**
 * Normalise a base64 image for use in an <img src>.
 *
 * The API accepts both a bare base64 blob and a full `data:` URL, and it
 * returns bare base64 from /leakcheck/example/screenshot. A bare blob assigned
 * to `src` renders as a broken image with no error worth reading, so the
 * prefix is added here, once, rather than at each call site.
 */
export function toImageDataUrl(b64) {
  if (typeof b64 !== 'string' || b64.length === 0) return null
  if (b64.startsWith('data:')) return b64
  return `data:image/png;base64,${b64}`
}

async function readDetail(res) {
  // The API returns {"detail": "..."} for both 400s and the 403/503 cases.
  // Falls back to the status line when the body is not JSON at all, which is
  // what a proxy error page looks like -- that is a real failure mode here,
  // since Vite answers for the API when the backend is down.
  try {
    const body = await res.json()
    if (body && typeof body.detail === 'string') return body.detail
    if (body && body.detail) return JSON.stringify(body.detail)
    return null
  } catch {
    return null
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const url = path
  let res
  try {
    res = await fetch(url, {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (e) {
    // Aborts are the caller's own doing (a superseded request); rethrow so the
    // caller can ignore them rather than rendering them as "backend down".
    if (e && e.name === 'AbortError') throw e
    throw new ApiError(BACKEND_HINT, { kind: 'unreachable', url })
  }

  if (!res.ok) {
    const detail = await readDetail(res)
    // A 5xx with no `detail` is the dev proxy talking, not the application.
    // Vite answers for /demo/* itself when nothing is listening upstream, and
    // it answers 500 text/plain -- verified, not assumed. Treating that as an
    // ordinary HTTP error would replace the one message that tells the reader
    // what to do ("start the backend") with "the backend answered 500 for
    // /demo/state", which is true and useless. A genuine application 500 still
    // carries its `detail` and is reported as itself.
    if (res.status >= 500 && detail === null) {
      throw new ApiError(BACKEND_HINT, {
        kind: 'unreachable',
        status: res.status,
        url,
      })
    }
    throw new ApiError(detail || `the backend answered ${res.status} for ${url}`, {
      kind: 'http',
      status: res.status,
      detail,
      url,
    })
  }

  try {
    return await res.json()
  } catch {
    throw new ApiError(`the backend sent a response that is not JSON for ${url}`, {
      kind: 'malformed',
      status: res.status,
      url,
    })
  }
}

const get = (path) => request(path)
const post = (path, body) => request(path, { method: 'POST', body })

/**
 * A GET that returns bytes rather than JSON, for the one route that serves a
 * file. Kept separate from `request` because `request`'s "always JSON, throw
 * otherwise" contract is what `isFailClosed` and `isUnreachable` are built on,
 * and weakening it to accommodate a download would cost every other screen.
 *
 * The order matters and is the reason this is a function rather than three
 * lines at the call site: a response body can only be read once, so the error
 * path has to be decided *before* `res.blob()` consumes it. Calling `.blob()`
 * first and then trying to read the detail would throw a second, unrelated
 * error and the user would see "the backend answered 404" with no reason.
 */
async function requestBlob(path, { signal } = {}) {
  let res
  try {
    res = await fetch(path, { signal })
  } catch (e) {
    if (e && e.name === 'AbortError') throw e
    throw new ApiError(BACKEND_HINT, { kind: 'unreachable', url: path })
  }

  if (!res.ok) {
    const detail = await readDetail(res)
    if (res.status >= 500 && detail === null) {
      throw new ApiError(BACKEND_HINT, {
        kind: 'unreachable',
        status: res.status,
        url: path,
      })
    }
    throw new ApiError(detail || `the backend answered ${res.status} for ${path}`, {
      kind: 'http',
      status: res.status,
      detail,
      url: path,
    })
  }

  const blob = await res.blob()
  return {
    blob,
    // The server's own name for the file, when it gave one. Null means the
    // caller names it, which it can always do -- it knows the doc id.
    filename: filenameFromDisposition(res.headers.get('Content-Disposition')),
    bytes: blob.size,
  }
}

export const api = {
  demoState: () => get('/demo/state'),
  documents: () => get('/demo/documents'),
  distribute: (payload) => post('/demo/distribute', payload),
  open: (payload) => post('/demo/open', payload),
  leak: (payload) => post('/demo/leak', payload),

  /**
   * The sealed container, as bytes. This is the file the whole "you cannot open
   * it without the server" claim is about: it is fetched over the same origin
   * as everything else, and it is useless the moment it lands.
   */
  downloadContainer: (docId, opts) =>
    requestBlob(`/demo/documents/${encodeURIComponent(docId)}.lfdoc`, opts),

  /**
   * The sealed container as raw bytes, for hashing in the browser.
   *
   * Distinct from `downloadContainer`, which hands back a Blob to save. This one
   * exists so a file the reader already holds can be compared against the
   * authority's copy of the same document -- the comparison that catches a
   * doctored header -- and bytes fetched for a comparison should never reach
   * disk as a side effect.
   */
  containerBytes: async (docId, opts) => {
    const { blob } = await requestBlob(
      `/demo/documents/${encodeURIComponent(docId)}.lfdoc`,
      opts,
    )
    return blob.arrayBuffer()
  },

  adminRecipients: () => get('/demo/admin/recipients'),
  revokeRecipient: (recipientId) =>
    post('/demo/admin/revoke', { recipient_id: recipientId }),
  reinstateRecipient: (recipientId) =>
    post('/demo/admin/reinstate', { recipient_id: recipientId }),

  leakcheck: (payload) => post('/leakcheck', payload),
  example: (kind) => get(`/leakcheck/example/${kind}`),

  ledgerHead: () => get('/ledger/head'),
  ledgerEntry: (index) => get(`/ledger/entry/${index}`),
  ledgerEntries: (limit = 50, order = 'desc') =>
    get(`/ledger/entries?limit=${limit}&order=${order}`),
  witnesses: () => get('/witnesses'),
  health: () => get('/health'),
  anchors: () => get('/anchors'),
}
