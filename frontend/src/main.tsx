import './index.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/app'
import { configureApi } from '@/lib/api'
import { createPersister } from '@/lib/offline-cache'
import { followBrowserOnline } from '@/lib/online'
import { createQueryClient } from '@/lib/query'
import { followTheme } from '@/lib/theme'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found')
}

configureApi()
// Back from signing in again at a proxy: the marker has done its work.
const url = new URL(window.location.href)
if (url.searchParams.has('signin')) {
  url.searchParams.delete('signin')
  window.history.replaceState(null, '', url)
}
followBrowserOnline()
followTheme()

createRoot(rootElement).render(
  <StrictMode>
    <App queryClient={createQueryClient()} persister={createPersister()} />
  </StrictMode>,
)
