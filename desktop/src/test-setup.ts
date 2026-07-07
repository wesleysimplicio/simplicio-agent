// Vitest setup (jsdom environment).
//
// jsdom does not implement the `window.CSS` namespace, but the renderer uses
// `CSS.escape` (e.g. src/components/assistant-ui/thread/timeline.tsx) when
// building attribute selectors. Polyfill just `CSS.escape` with the spec
// algorithm (https://drafts.csswg.org/cssom/#serialize-an-identifier) so
// component tests exercise the same code path as the real browser.

function cssEscape(value: string): string {
  const string = String(value)
  const length = string.length
  const firstCodeUnit = string.charCodeAt(0)
  let result = ''

  for (let index = 0; index < length; index++) {
    const codeUnit = string.charCodeAt(index)

    // U+0000 NULL becomes U+FFFD REPLACEMENT CHARACTER.
    if (codeUnit === 0x0000) {
      result += '�'
      continue
    }

    if (
      // Control characters and U+007F DELETE are escaped as code points.
      (codeUnit >= 0x0001 && codeUnit <= 0x001f) ||
      codeUnit === 0x007f ||
      // A digit as the first character, or as the second after a leading "-".
      (index === 0 && codeUnit >= 0x0030 && codeUnit <= 0x0039) ||
      (index === 1 && codeUnit >= 0x0030 && codeUnit <= 0x0039 && firstCodeUnit === 0x002d)
    ) {
      result += `\\${codeUnit.toString(16)} `
      continue
    }

    // A lone "-" is escaped so it does not read as a hyphen-minus prefix.
    if (index === 0 && length === 1 && codeUnit === 0x002d) {
      result += `\\${string.charAt(index)}`
      continue
    }

    // Alphanumerics, "-" and "_" pass through; everything else is backslashed.
    if (
      codeUnit >= 0x0080 ||
      codeUnit === 0x002d ||
      codeUnit === 0x005f ||
      (codeUnit >= 0x0030 && codeUnit <= 0x0039) ||
      (codeUnit >= 0x0041 && codeUnit <= 0x005a) ||
      (codeUnit >= 0x0061 && codeUnit <= 0x007a)
    ) {
      result += string.charAt(index)
      continue
    }

    result += `\\${string.charAt(index)}`
  }

  return result
}

const globalWithCss = globalThis as { CSS?: { escape?: (value: string) => string } }

if (typeof globalWithCss.CSS === 'undefined') {
  globalWithCss.CSS = { escape: cssEscape }
} else if (typeof globalWithCss.CSS.escape !== 'function') {
  globalWithCss.CSS.escape = cssEscape
}
