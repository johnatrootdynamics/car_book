# Track ops brand assets

The horizontal logo is the approved tactical artwork from the logo design conversation. `BrandLogo.tsx` displays the original PNG through a cropped viewport, preserving the artwork without the presentation margins. The web portal uses the same image in `racetrack/static/brand/track-ops-logo.png` and the shared `brand_logo.html` template.

- `track-ops-logo.png`: approved horizontal artwork, 2172 × 724.
- `track-ops-icon.png`: opaque 1024 × 1024 app icon and splash artwork.
- `track-ops-adaptive-icon.png`: Android foreground with additional safe-area padding.
- Web favicon: `racetrack/static/brand/favicon.png`.

Keep `mobile/lib/theme.ts` and `racetrack/static/brand.css` aligned: charcoal `#111827`, off-white `#F1F5F9`, blue actions `#2563EB`, and light-blue text accents `#7DBBFF`. Green, amber, and red communicate operational status. QR codes retain a dark foreground and white quiet zone.

App icon, launch screen, and system appearance changes require a new native build. For an existing generated native project, sync configuration with `npx expo prebuild --no-install` before building. The existing local iOS icon, splash artwork, and appearance were also synchronized during this integration.

## Asset provenance

The approved logo and the icon companion were produced with the built-in image generation tool. The original approved logo was copied unchanged. Icon resizing and Android padding are packaging steps.

Icon generation prompt:

> Use case: logo-brand. Create the square app icon companion to this approved Track ops logo. Extract and faithfully preserve ONLY the angular blue track/T symbol from the LEFT of the input. No lettering. Same exact chamfered T top bar, separate short vertical T stem, and parallel bent racing lanes forming the right-facing motion mark; keep its proportions, geometry and blue colors. Center this symbol in a square solid dark charcoal #111827 canvas. The symbol should occupy approximately 62 percent of the canvas width, with generous even clear space for operating-system icon cropping. Flat solid colors, crisp clean edges, no texture, no gradients, no mockup, no shadows, no new graphic elements, no text. Fully opaque square canvas.
