#!/usr/bin/env python3
"""List inner HTML pages missing the premium design hook.

Every page except the homepage shell (repo-root index.html) must:
  - set data-premium on the opening <html> tag
  - load /assets/premium.css

The homepage stays unmarked so its directory layout is unchanged.
There is no separate category-page generator in this repo; new HTML
must pass this check. Run with --fix to insert the hook.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = '<link rel="stylesheet" href="/assets/premium.css">'
HOME = ROOT / "index.html"


def html_files():
    files = []
    for path in sorted(ROOT.rglob("*.html")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        if path.resolve() == HOME.resolve():
            continue
        files.append(path)
    return files


def opening_html(text: str) -> str | None:
    start = text.find("<html")
    if start < 0:
        return None
    end = text.find(">", start)
    if end < 0:
        return None
    return text[start : end + 1]


def missing_reasons(text: str) -> list[str]:
    reasons = []
    tag = opening_html(text)
    if tag is None or "data-premium" not in tag:
        reasons.append("data-premium")
    if 'href="/assets/premium.css"' not in text:
        reasons.append("premium.css")
    return reasons


def apply_hook(text: str) -> str:
    tag = opening_html(text)
    if tag is None:
        raise SystemExit("no <html> tag")
    if "data-premium" not in tag:
        text = text.replace(tag, tag[:-1] + " data-premium>", 1)
    if 'href="/assets/premium.css"' not in text:
        if "</head>" not in text:
            raise SystemExit("no </head>")
        text = text.replace("</head>", LINK + "</head>", 1)
    return text


def main() -> int:
    fix = "--fix" in sys.argv
    missing = []
    for path in html_files():
        text = path.read_text(encoding="utf-8")
        reasons = missing_reasons(text)
        if not reasons:
            continue
        missing.append((path.relative_to(ROOT).as_posix(), ",".join(reasons)))
        if fix:
            path.write_text(apply_hook(text), encoding="utf-8")
    if missing and not fix:
        for rel, why in missing:
            print(f"{rel}\t{why}")
        print(f"{len(missing)} missing", file=sys.stderr)
        return 1
    if missing and fix:
        print(f"fixed {len(missing)}")
        return 0
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
