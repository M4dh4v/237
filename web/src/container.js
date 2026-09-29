// The `.lfdoc` container, parsed in the browser.
//
// This is a second implementation of `logfirst/sealed.py`, and that is worth
// being explicit about rather than glossing over: `unpack` is the definition,
// this mirrors it, and two implementations of a binary format drift. What keeps
// them together is `tests/test_container_js.py`, which parses a real container
// produced by the Python side with this file and asserts the two agree, plus the
// malformed cases, which have to raise on both sides. That test is why the magic
// below is written out byte by byte with its length taken from the array: an
// earlier draft of this file had the length one byte too long, which would have
// rejected every genuine container with a message about a bad magic string.
//
// What the header *means* is in the Python module's docstring, and it is the
// part that is easy to get wrong: **it is unauthenticated.** The AEAD's
// additional data is only the `doc_id`, so the classification, the page count
// and the pdf hash can be edited by anyone holding the file. It is a label.
// `compareLabels` is what checks it against the manifest that travelled inside
// the encryption -- and that is only available after an open.

// "LFDOC\0\1" -- seven bytes, not eight.
const MAGIC = new Uint8Array([0x4c, 0x46, 0x44, 0x4f, 0x43, 0x00, 0x01])
const HEADER_LEN_BYTES = 4
const MAX_HEADER = 1 << 20 // mirrors sealed._MAX_HEADER

/** The fields the container header and the sealed manifest both carry. */
export const AGREED_FIELDS = [
  'doc_id',
  'classification',
  'doc_hash',
  'pdf_hash',
  'font',
  'pages',
  'created',
]

export class ContainerError extends Error {
  constructor(message) {
    super(message)
    this.name = 'ContainerError'
  }
}

/**
 * Parse a container from an ArrayBuffer.
 *
 * Returns `{ header, headerBytes, ciphertextBytes, totalBytes }` -- what a
 * reader can know while holding no key. The ciphertext is the tail of the file
 * and is never decoded here; nothing in this module can decrypt anything.
 */
export function parseContainer(buffer) {
  const bytes = new Uint8Array(buffer)
  const start = MAGIC.length + HEADER_LEN_BYTES
  if (bytes.length < start) {
    throw new ContainerError(
      `a container is at least ${start} bytes; this file is ${bytes.length}`,
    )
  }
  for (let i = 0; i < MAGIC.length; i += 1) {
    if (bytes[i] !== MAGIC[i]) {
      throw new ContainerError(
        'not a .lfdoc container (bad magic or unknown version)',
      )
    }
  }

  const headerLen = new DataView(buffer).getUint32(MAGIC.length, false)
  if (headerLen > MAX_HEADER) {
    throw new ContainerError(`container declares a ${headerLen}-byte header`)
  }
  if (bytes.length < start + headerLen) {
    throw new ContainerError('container ends inside its header')
  }

  let header
  try {
    // fatal:true so invalid UTF-8 raises here, as it does in Python, rather
    // than being silently replaced with U+FFFD and then failing as bad JSON.
    const text = new TextDecoder('utf-8', { fatal: true }).decode(
      bytes.subarray(start, start + headerLen),
    )
    header = JSON.parse(text)
  } catch (e) {
    throw new ContainerError(`container header is not JSON: ${e.message}`)
  }
  if (header === null || typeof header !== 'object' || Array.isArray(header)) {
    throw new ContainerError('container header is not an object')
  }

  return {
    header,
    headerBytes: headerLen,
    ciphertextBytes: bytes.length - start - headerLen,
    totalBytes: bytes.length,
  }
}

/**
 * Fields where the container's label disagrees with the sealed manifest.
 *
 * The mirror of `sealed.compare`, including the case that is easy to miss: a
 * field present in one and absent from the other is a disagreement, because
 * that is one side declining to be checked. An empty array means they agree.
 */
export function compareLabels(header, manifest) {
  const bad = []
  for (const field of AGREED_FIELDS) {
    const inHeader = header != null && Object.hasOwn(header, field)
    const inManifest = manifest != null && Object.hasOwn(manifest, field)
    if (inHeader !== inManifest) bad.push(field)
    else if (inHeader && header[field] !== manifest[field]) bad.push(field)
  }
  return bad
}

/**
 * The SHA-256 of a buffer, as hex.
 *
 * Throws when `crypto.subtle` is missing rather than returning null. It needs a
 * secure context, and this particular hash is the check that stands between a
 * doctored label and a PDF from the wrong document -- so a silent pass here
 * would be the worst possible failure of the whole page.
 */
export async function sha256Hex(buffer) {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) {
    throw new ContainerError(
      'this browser will not compute a SHA-256 here: crypto.subtle needs a ' +
        'secure context (https, or localhost)',
    )
  }
  const digest = await subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}
