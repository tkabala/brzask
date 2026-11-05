// Icons for the installed app: `pnpm icons` writes them next to public/icon.svg.
// Maskable and Apple icons fill the whole square with the icon's own background.
export default {
  headLinkOptions: { preset: '2023' },
  preset: {
    transparent: { sizes: [64, 192, 512], favicons: [[48, 'favicon.ico']] },
    maskable: { sizes: [512], padding: 0.3, resizeOptions: { background: '#171717' } },
    apple: { sizes: [180], padding: 0.3, resizeOptions: { background: '#171717' } },
  },
  images: ['public/icon.svg'],
}
