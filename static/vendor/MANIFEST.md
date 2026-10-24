# Local Vendor Assets

This folder contains third-party assets mirrored locally so the app can load without CDN access.

## JavaScript

- `js/lucide.js`: local mirror of `https://unpkg.com/lucide@latest`
- `js/three-0.160.0.module.js`: local mirror of `https://unpkg.com/three@0.160.0/build/three.module.js`

## CSS

- `css/fonts.css`: local `@font-face` declarations used by all pages.
- `css/tailwind.css`: precompiled Tailwind utilities (26KB minified), generated from `tools/tailwind-build` by scanning `static/**/*.html` + `static/js/**/*.js`. Regenerate after adding new Tailwind classes: `cd tools/tailwind-build && npm run build`.

- `fonts/montserrat-400.ttf`: Montserrat 400
- `fonts/montserrat-500.ttf`: Montserrat 500
- `fonts/montserrat-600.ttf`: Montserrat 600
- `fonts/montserrat-700.ttf`: Montserrat 700
- `fonts/space-grotesk-9.ttf`: Space Grotesk 300
- `fonts/space-grotesk-10.ttf`: Space Grotesk 400 / 500
- `fonts/space-grotesk-8.ttf`: Space Grotesk 600 / 700
- `fonts/jetbrains-mono-7.ttf`: JetBrains Mono 400
- `fonts/jetbrains-mono-6.ttf`: JetBrains Mono 700

Note: Chinese font resolution follows standard web font stack fallback (`"Source Han Sans SC"`, `"PingFang SC"`, `"Microsoft YaHei UI"`, `"Microsoft YaHei"`, sans-serif) using system-installed fonts to avoid bundling 40MB+ full CJK font binaries.

