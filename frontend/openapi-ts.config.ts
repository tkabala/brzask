import { defineConfig } from '@hey-api/openapi-ts'

// The client is generated from the committed OpenAPI document; CI fails when
// src/client differs from what `pnpm generate` produces.
export default defineConfig({
  input: '../openapi.json',
  output: { path: 'src/client', postProcess: ['prettier'] },
  plugins: [
    '@hey-api/client-fetch',
    '@hey-api/typescript',
    '@hey-api/sdk',
    'zod',
    '@tanstack/react-query',
  ],
})
