// Copy the vendored woff2 out of the installed @fontsource packages into
// web/public/fonts/ under the names fonts.css expects. Runs offline (no network)
// after `npm install`. Idempotent. Air-gap rule: fonts ship in the repo/public,
// never a CDN.
import { mkdirSync, copyFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const out = join(root, 'public', 'fonts')
mkdirSync(out, { recursive: true })

// src filename in @fontsource/<pkg>/files  ->  dest filename in public/fonts
const MAP = [
  ['space-grotesk', 'space-grotesk-latin-500-normal.woff2', 'space-grotesk-500.woff2'],
  ['space-grotesk', 'space-grotesk-latin-700-normal.woff2', 'space-grotesk-700.woff2'],
  ['inter', 'inter-latin-400-normal.woff2', 'inter-400.woff2'],
  ['inter', 'inter-latin-500-normal.woff2', 'inter-500.woff2'],
  ['inter', 'inter-latin-600-normal.woff2', 'inter-600.woff2'],
  ['jetbrains-mono', 'jetbrains-mono-latin-400-normal.woff2', 'jetbrains-mono-400.woff2'],
  ['jetbrains-mono', 'jetbrains-mono-latin-500-normal.woff2', 'jetbrains-mono-500.woff2'],
]

let ok = 0
const missing = []
for (const [pkg, srcName, destName] of MAP) {
  const src = join(root, 'node_modules', '@fontsource', pkg, 'files', srcName)
  if (!existsSync(src)) {
    missing.push(`@fontsource/${pkg}/files/${srcName}`)
    continue
  }
  copyFileSync(src, join(out, destName))
  ok++
}

console.log(`vendored ${ok}/${MAP.length} font files -> public/fonts/`)
if (missing.length) {
  console.error('MISSING (install @fontsource packages first):\n  ' + missing.join('\n  '))
  process.exit(1)
}
