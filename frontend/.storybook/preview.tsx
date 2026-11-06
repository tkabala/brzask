import '../src/index.css'

import type { Preview } from '@storybook/react-vite'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { mswLoader } from 'msw-storybook-addon/csf3'
import { I18nextProvider } from 'react-i18next'

import { handlers, resetDemo } from '../src/demo/handlers'
import { initI18n, LANGUAGES } from '../src/i18n'
import { configureApi } from '../src/lib/api'
import { applyTheme, type Theme } from '../src/lib/theme'

configureApi()

const preview: Preview = {
  loaders: [mswLoader()],
  parameters: {
    // Every story can reach the demo API; a story may override single handlers.
    msw: { handlers: { api: handlers } },
  },
  beforeEach: () => {
    resetDemo()
  },
  globalTypes: {
    locale: {
      description: 'Language',
      toolbar: {
        icon: 'globe',
        items: Object.entries(LANGUAGES).map(([value, title]) => ({ value, title })),
      },
    },
    theme: {
      description: 'Theme',
      toolbar: {
        icon: 'mirror',
        items: [
          { value: 'light', title: 'Light', icon: 'sun' },
          { value: 'dark', title: 'Dark', icon: 'moon' },
        ],
      },
    },
  },
  initialGlobals: { locale: 'en', theme: 'light' },
  decorators: [
    (Story, context) => {
      const i18n = initI18n(context.globals.locale as 'en' | 'pl')
      applyTheme(context.globals.theme as Theme)
      // Pages render the whole app, with its own router and query client.
      if (context.parameters.app === true) return <Story />
      // Views take their data as props; a client only backs components that
      // run their own mutations, which stories never trigger.
      const queryClient = new QueryClient()
      // Views link to routes; a one-route router gives links somewhere to point.
      const router = createRouter({
        routeTree: createRootRoute({
          component: () => (
            <div className="mx-auto max-w-2xl bg-background p-4 text-foreground">
              <Story />
            </div>
          ),
        }),
        history: createMemoryHistory({ initialEntries: ['/'] }),
      })
      return (
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </I18nextProvider>
      )
    },
  ],
}

export default preview
