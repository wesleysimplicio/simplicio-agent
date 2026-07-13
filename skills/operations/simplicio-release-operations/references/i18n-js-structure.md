# i18n.js Structure & Pitfalls

## File: `site/assets/js/i18n.js` (~1332 lines, 15 languages)

## Architecture

```
I18N = {
  en: { ... },       // lines 14-117 — complete translation
  es: { ... },       // lines 118-231 — complete translation
};
HOME = { en: {...}, es: {...}, fr: {...}, ... };   // merged via Object.assign
LAB  = { en: {...}, es: {...}, fr: {...}, ... };   // merged via Object.assign
SIMPLICIO_EXTRA = { en: {...}, es: {...}, ... };   // merged via Object.assign
```

## Language Resolution Chain

The `applyLang(lang)` function does:
1. `dict = I18N[lang]` — reads the language sub-object
2. If `dict[k] == null`, skips (keeps HTML default — pt-BR inline text)
3. Never reads `I18N` directly

For en/es: translations come from `I18N.en` / `I18N.es`
For the other 13: translations from HOME + LAB + SIMPLICIO_EXTRA merged via `Object.assign()`

## Key Merge Objects

| Object | What it covers |
|--------|---------------|
| HOME | Main landing page (h_tag, h_h1, h_lead, h_cta1) |
| LAB | AI Labs page (lab_h1, lab_enter, lab_foot) |
| SIMPLICIO_EXTRA | Simplicio page extras (docs_uninstall_*, pt-BR defaults) |

## CRITICAL PITFALLS

### PITFALL 1: Stray `},` lines break the entire language selector

**Symptom:** `<select id="lang">` shows 0 options. Page loads but no translations work.

**Root cause:** Orphan `  },` lines inside the `I18N` object close the parent object
prematurely. Everything below becomes top-level code, causing a
`SyntaxError: Missing initializer in const declaration`.

**Fix:** 
```bash
grep -n '^  },' i18n.js
# Lines 128 and 243 close `en` and `es` blocks — KEEP those.
# ALL OTHER `},` lines between line 244 and `};` are ORPHANS — REMOVE them.
```

**Prevention:** After ANY edit to i18n.js:
```bash
node --check /path/to/i18n.js
# Must exit 0. If it shows a syntax error, fix before deploying.
```

### PITFALL 2: Python regex corrupts language blocks silently

**Symptom:** After a bulk regex find-replace across language blocks, all languages
show the same wrong translation (usually Spanish).

**Root cause:** Language detection via backward regex search from match position
cannot reliably locate the enclosing language block in a file with nested objects
and comment lines. `re.DOTALL` patterns silently cross block boundaries.

**Wrong (DON'T USE):**
```python
content = re.sub(r"docs_faq_1a:\s*'[^']*'", replace_faq, content)
```

**Right approaches:**
1. Use `patch` tool with exact `old_string`/`new_string` per language
2. Line-by-line processing that tracks `current_lang` via `  xx: {` openers
3. Update only the HTML default and remove i18n overrides (languages fall back to pt-BR)

### PITFALL 3: `{code1}` placeholders break brace counting

**Symptom:** Python parsing of JS object literals goes wrong — brace depth tracking
goes negative.

**Root cause:** String values like `'The binary lives at {code1}. Add to PATH: {code2}.'`
contain `{ }` characters inside single-quoted strings. Naive brace counters treat
them as object delimiters.

**Fix:** Use `patch` tool line-by-line. Don't parse JS with Python regex.

### PITFALL 4: Pricing appears in 4+ independent locations

When changing pricing (e.g. "7-day trial / $10/mo" → "free beta"):

| Location | Keys |
|----------|------|
| HTML defaults | `price_*`, `docs_faq_1a` |
| I18N.en | `price_eyebrow`, `price_h2`, `price_sub`, `price_badge`, `price_per`, `price_brl`, `price_card`, `ft_tag`, `docs_faq_1a` |
| I18N.es | Same keys as en |
| LAB (15 languages) | `lab_foot` |
| READMEs (15 languages) | Beta section in each file |

**Verification after changes:**
```bash
grep -c '\$10\|10\$' i18n.js    # Must return 0
grep -rn '30/06/2026' READMEs/  # Must return nothing
```
