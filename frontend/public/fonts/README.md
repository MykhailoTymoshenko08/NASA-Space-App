# Map label glyphs

MapLibre needs label fonts as SDF glyph ranges (`{fontstack}/{range}.pbf`). These are self-hosted so the map makes no requests outside our app.

- Fonts: Noto Sans Regular and Noto Sans Medium, SIL Open Font License 1.1 (`OFL.txt`).
- Source: https://github.com/protomaps/basemaps-assets/tree/main/fonts
- Ranges: `0-255` (Basic Latin, Latin-1), `256-511` (Latin Extended-A/B), `8192-8447` (General Punctuation, e.g. typographic quotes). US place names only need these.
- Used by `src/shared/ui/map/map-style.ts` (`glyphs`).
