# Release v1.0.0 — Session Notes (2026-06-16)

## What was delivered

- **Tag v1.0.0** on both `simplicio-runtime` AND `simplicio` (public) repos
- **macOS ARM64** binary: 17MB, site `dist/simplicio-darwin-arm64`
- **macOS x86_64** binary: 20MB, site `dist/simplicio-darwin-x64`
- **README**: 15 languages, 96% token savings claim, flashy badges
- **install.sh**: free version message, update notification, no auto-update scheduler
- **Site**: hero overlay (rgba 0,0,0,0.60), removed "7 days free" and "Install free" from nav/banner
- **Legal pages**: `/privacidade.html` and `/termos.html` at site root
- **Docs**: 15 languages via i18n.js

## What failed

- **CI (GitHub Actions)**: billing limit — all workflows fail immediately
- **zigbuild cross-compilation**: C deps (libgomp, lmdb) can't cross-compile from macOS ARM64
- **Windows/Linux v1.0.0 binaries**: not produced; site still has v0.9.4 Windows binary

## Key decisions

- Free version = no auto-update scheduler registered + manual `simplicio update check` message
- "Beta gratuita" instead of "7 dias grátis" in meta tags
- Overlay at 60% opacity to keep text readable over background effects
- Source code of simplicio-runtime NEVER exposed — public repo has only binaries, scripts, READMEs

## Site paths updated

- `site/simplicio/index.html` — hero overlay, removed "7 dias grátis" + "Instalar grátis", added Com vs Sem + CLI/Plugin/Skill/Desktop sections
- `site/simplicio/docs.html` — removed install button from nav
- `site/assets/css/simpleti.css` — `.hero-overlay` styles + `position: relative` on `.hero`, `.compare-grid` styles, `.grid.c4` styles
- `site/privacidade.html` — new
- `site/termos.html` — new
- `site/simplicio/install.sh` — free version message block
- `site/simplicio/version.txt` — "1.0.0"
- `site/simplicio/dist/simplicio-darwin-arm64` — 17MB
- `site/simplicio/dist/simplicio-darwin-x64` — 20MB

## New site sections added

### Com vs Sem Simplicio (#compare)
- Two-column comparison: ❌ bad (red-tinted) vs ✅ good (green-tinted)
- Stats row: 96% economia, 2,7× faster, 52× fewer tokens, 177 ns cache
- Uses `.compare-grid` + `.compare-col.bad|.good` CSS classes

### CLI · Plugin · Skill · Desktop (#modos)
- 4-column grid (`.grid.c4`) showing all installation modes
- CLI: `curl | sh`, Plugin MCP: `simplicio mcp register`, Skill: `--with-claude`, Desktop: `.pkg/.msi`

## Section removed

- **"Os comandos que economizam"** (#cmd) — removed per user request. HTML section, nav links (header + footer), and all 240+ i18n lines across 15 languages (`cmd_*` keys) deleted.

## Mobile CSS fixes applied

- `code.mini`: `white-space: nowrap` → `white-space: normal; word-break: break-all; max-width: 100%`
- `.card`: added `overflow: hidden; max-width: 100%`
- Added 480px tablet breakpoint for `.grid.c3` and `.grid.c4` to get 2 columns before 720px 3/4-column layout

### i18n pitfall — updating site text
When the user says "remove X from the header" or "change Y on the page", you MUST:
1. Update the HTML default text (the inline content in `data-i18n` elements)
2. Find and update ALL 15 language entries for that key in `assets/js/i18n.js`
3. Also check `<meta>` tags, OG tags, and footer links for the same text
Skipping the i18n.js update means non-PT users still see the old text.

## PATH fix (Homebrew Rust vs rustup)

The session hit repeated `E0463: can't find crate for core` errors because
Homebrew's Rust was on PATH. The fix documented in the parent skill's
cross-compilation section was essential — without it, every non-native target
fails.
