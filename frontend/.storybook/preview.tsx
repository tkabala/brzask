import '../src/index.css'

import type { Preview } from '@storybook/react-vite'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { I18nextProvider } from 'react-i18next'

import { initI18n, LANGUAGES } from '../src/i18n'

const preview: Preview = {
  globalTypes: {
    locale: {
      description: 'Language',
      toolbar: {
        icon: 'globe',
        items: Object.entries(LANGUAGES).map(([value, title]) => ({ value, title })),
      },
    },
  },
  initialGlobals: { locale: 'en' },
  decorators: [
    (Story, context) => {
      const i18n = initI18n(context.globals.locale as 'en' | 'pl')
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
