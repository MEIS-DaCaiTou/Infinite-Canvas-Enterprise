# Local Vendor Assets

This folder contains third-party assets mirrored locally so the app can load without CDN access.

## JavaScript

- `js/tailwindcss-cdn.js`: local mirror of `https://cdn.tailwindcss.com`
- `js/lucide.js`: local mirror of `https://unpkg.com/lucide@latest`
- `js/three-0.160.0.module.js`: local mirror of `https://unpkg.com/three@0.160.0/build/three.module.js`
- `three-addons-r160/`: Three r160 MIT GLTF/Draco loading helpers and BufferGeometryUtils, with original license and provenance; bare imports map to the existing local Three core.
- `liblib-character-motion/`: the original Liblib `midwam-human.glb`, recovered preview renderer, and local Draco WASM decoder used by the accepted development preview. The owner explicitly requested this exact model on 2026-10-29. Source/adaptations are recorded in SOURCE.json and NOTICE; original renderer/model are not represented as MIT or CC0. Draco and Three retain their own notices.
- The parity candidate always loads this packaged renderer in both canvases. It does not switch by the presence of developer-only reference files, and does not use the rejected CC0 replacement. Liblib business APIs, analytics, account data and reference character photos are not included.
- Current published10.11 remains unchanged; this delivery-parity fix is carried by the owner-authorized standalone repository branch, not yet merged or released.

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
