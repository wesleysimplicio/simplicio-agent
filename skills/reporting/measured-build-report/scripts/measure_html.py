#!/usr/bin/env python3
"""Deterministic metric probe for a single-file HTML deliverable.

Usage:
  python3 measure_html.py <file.html> [--features '{"Label":"regex",...}']

Prints JSON with measured metrics. No external deps. Re-runnable so the
agent never hand-types numbers (which invites fabrication).

Features are measured by regex token presence in the source -- evidence,
not assertion. Derived values (cells_per_side) are computed, not guessed.
"""
import sys, re, json, os
from html.parser import HTMLParser


class _Validator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.void = {'meta','link','br','hr','img','input','area','base',
                     'col','embed','source','track','wbr'}
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.errors.append("stray </%s>" % tag)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: measure_html.py <file> [--features JSON]"}))
        sys.exit(2)

    path = sys.argv[1]
    feats = {}
    if "--features" in sys.argv:
        idx = sys.argv.index("--features")
        feats = json.loads(sys.argv[idx + 1])

    with open(path, encoding="utf-8") as f:
        src = f.read()

    v = _Validator()
    v.feed(src)

    css = re.search(r"<style>(.*?)</style>", src, re.S)
    css_text = css.group(1) if css else ""
    js = re.search(r"<script>(.*?)</script>", src, re.S)
    js_text = js.group(1) if js else ""

    size = re.search(r"SIZE\s*=\s*(\d+)", js_text)
    grid = re.search(r"GRID\s*=\s*(\d+)", js_text)
    cells = (int(size.group(1)) // int(grid.group(1))) if (size and grid) else None

    feat_out = {label: bool(re.search(pat, src)) for label, pat in feats.items()}

    out = {
        "path": path,
        "bytes": os.path.getsize(path),
        "lines": src.count("\n") + 1,
        "words": len(src.split()),
        "html_parse_errors": v.errors,
        "unclosed_tags": v.stack,
        "css_rules_approx": css_text.count("{"),
        "css_vars": len(re.findall(r"--[\w-]+:", css_text)),
        "js_functions_approx": len(re.findall(r"function\s+\w+|=>\s*\{", js_text)),
        "event_listeners": len(re.findall(r"addEventListener", js_text)),
        "canvas_count": len(re.findall(r"<canvas", src)),
        "cells_per_side": cells,
        "features": feat_out,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
