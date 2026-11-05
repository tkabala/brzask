import './index.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/app'
import { configureApi } from '@/lib/api'
import { createPersister } from '@/lib/offline-cache'
import { createQueryClient } from '@/lib/query'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found')
}

configureApi()

createRoot(rootElement).render(
  <StrictMode>
    <App queryClient={createQueryClient()} persister={createPersister()} />
  </StrictMode>,
)
