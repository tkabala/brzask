import type { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.tsx'],
  addons: ['msw-storybook-addon'],
  framework: { name: '@storybook/react-vite', options: {} },
  // The mock service worker lives here, not in public/, so the app never ships it.
  staticDirs: ['./public'],
  core: { disableTelemetry: true },
}

export default config
