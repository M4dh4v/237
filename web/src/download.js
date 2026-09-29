// Turning a response the backend described into a file the browser saves.
//
// Three small things, kept here rather than inline in the component, because
// each one is easy to get subtly wrong and the wrongness is invisible until
// someone's download is a 0-byte file called "document".
//
// **Object URLs are leaked unless they are revoked.** `URL.createObjectURL`
// pins the Blob in memory for the life of the document; a demo where you click
// download a few dozen times accumulates every one of them. So `saveBlob`
// revokes what it created, and it does it on a later tick rather than
// immediately -- revoking in the same turn as the click can cancel the download
// in some browsers, which is the kind of bug that only shows up on someone
// else's machine.
//
// **`Content-Disposition` is a header, not a filename.** It arrives as
// `attachment; filename="DOC-0000.lfdoc"` or with an RFC 5987
// `filename*=UTF-8''...` form, and it may be absent entirely. It is parsed
// rather than trusted, and the fallback is always a name the caller supplied.

/**
 * Decode standard base64 into a Blob.
 *
 * `atob` gives a binary string, which is *not* the same as the bytes: every
 * code unit above 0x7F has to be taken modulo 256 before it goes into the
 * Uint8Array. Skipping that step corrupts exactly the bytes a PNG or a PDF
 * starts with, so the file arrives looking plausible and will not open.
 */
export function base64ToBlob(b64, type = 'application/octet-stream') {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type })
}

/**
 * Pull a filename out of a `Content-Disposition` header.
 *
 * Returns null when the header is missing or carries nothing usable, so the
 * caller's own fallback wins. The RFC 5987 form is checked first because a
 * server that sends both means the extended one.
 */
export function filenameFromDisposition(header) {
  if (typeof header !== 'string' || header.length === 0) return null
  const extended = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (extended) {
    try {
      return decodeURIComponent(extended[1].trim())
    } catch {
      // A malformed escape is not worth failing a download over; fall through
      // to the plain form below.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain ? plain[1].trim() : null
}

/** Save a Blob under `filename`, then release the object URL. */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Deferred: see the note at the top of this file.
  setTimeout(() => URL.revokeObjectURL(url), 0)
  return filename
}
