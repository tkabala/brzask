import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { APP_PORT, E2E_PASSWORD_HASH } from '../playwright.config.ts'

const stack = fileURLToPath(new URL('./stack.sh', import.meta.url))

function run(command: 'up' | 'down'): void {
  execFileSync(stack, [command], {
    stdio: 'inherit',
    env: { ...process.env, E2E_PORT: String(APP_PORT), E2E_PASSWORD_HASH },
  })
}

/** Starts the compose stack with demo data; the returned teardown removes it. */
export default function globalSetup(): () => void {
  run('up')
  return () => {
    run('down')
  }
}
