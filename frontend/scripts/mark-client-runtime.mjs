// The generator copies its fetch runtime into src/client/client and
// src/client/core. That runtime does not compile under this project's
// exactOptionalPropertyTypes, so it is left out of type checking; the code
// generated from openapi.json (types, SDK, schemas, queries) stays checked.
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const MARK = '// @ts-nocheck: copied generator runtime, see scripts/mark-client-runtime.mjs\n'

for (const directory of ['src/client/client', 'src/client/core']) {
  for (const name of await readdir(directory)) {
    if (!name.endsWith('.ts')) continue
    const path = join(directory, name)
    const source = await readFile(path, 'utf8')
    if (!source.startsWith(MARK)) await writeFile(path, MARK + source)
  }
}
