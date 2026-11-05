import type { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.tsx'],
  addons: ['msw-storybook-addon'],
  framework: { name: '@storybook/react-vite', options: {} },
  // The mock service worker lives here, not in public/, so the app never ships it.
  staticDirs: ['./public'],
  core: { disableTelemetry: true },
  // Stories are no installable app: leave out the service worker and manifest.
  viteFinal: (viteConfig) => ({
    ...viteConfig,
    plugins: (viteConfig.plugins ?? [])
      .flat()
      .filter(
        (plugin) => !(plugin && 'name' in plugin && plugin.name.startsWith('vite-plugin-pwa')),
      ),
  }),
}

export default config
