import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync, constants } from 'node:zlib'

const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]))
let n = 0
for (const f of walk('dist')) {
  if (!/\.(js|css|html|svg|json)$/.test(f)) continue
  writeFileSync(f + '.gz', gzipSync(readFileSync(f), { level: constants.Z_BEST_COMPRESSION }))
  n++
}
console.log(`gzip: ${n} files`)
