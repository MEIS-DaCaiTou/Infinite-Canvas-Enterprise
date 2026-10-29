# Local Vendor Assets

This folder contains third-party assets mirrored locally so the app can load without CDN access.

## JavaScript

- `js/tailwindcss-cdn.js`: local mirror of `https://cdn.tailwindcss.com`
- `js/lucide.js`: local mirror of `https://unpkg.com/lucide@latest`
- `js/three-0.160.0.module.js`: local mirror of `https://unpkg.com/three@0.160.0/build/three.module.js`
- Optional local comparison only: `three-addons-r160/` contains npm `three@0.160.0` MIT loading helpers. These helpers are not needed by the bundled geometric character placeholder and are excluded from the pre-assets PR together with the optional comparison renderer.

The owner-requested local Liblib comparison is separate from these open-source vendor licenses: recovered preview code and model/image provenance are recorded in `static/characters/motion/SOURCE.json` and `static/characters/reference/SOURCE.json`. Their redistribution rights have not been established; these comparison files remain untracked locally and are excluded from the public PR and formal delivery. No Liblib account API, bundler runtime or analytics code is executed by the adapted modules.

## CSS

- `css/fonts.css`: local `@font-face` declarations used by all pages.

## Fonts

- `fonts/inter-5.ttf`: Inter 300
- `fonts/inter-4.ttf`: Inter 400
- `fonts/inter-3.ttf`: Inter 500
- `fonts/inter-2.ttf`: Inter 600
- `fonts/inter-1.ttf`: Inter 800
- `fonts/jetbrains-mono-7.ttf`: JetBrains Mono 400
- `fonts/jetbrains-mono-6.ttf`: JetBrains Mono 700
- `fonts/space-grotesk-9.ttf`: Space Grotesk 300
- `fonts/space-grotesk-10.ttf`: Space Grotesk 500
- `fonts/space-grotesk-8.ttf`: Space Grotesk 700
