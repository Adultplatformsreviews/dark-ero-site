#!/usr/bin/env python3
"""Shrink homepage and category HTML so mobile Lighthouse can stay at 100.

Keeps the 21 primary homepage columns (already capped at 15 sites) and a
crawlable link for every other category. Category pages drop the repeated
full-site columns; each category page still lists its own sites, and SEE ALL
links that page.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = {
    "cat-adult-video", "cat-premium", "cat-live-cams", "cat-ai", "cat-hentai",
    "cat-adult-games", "cat-creator-platforms", "cat-sell-feet-pics", "cat-regional",
    "cat-orientation", "cat-fetish", "cat-body-themes", "cat-adult-themes", "cat-vr",
    "cat-erotic-content", "cat-stories-audio", "cat-images", "cat-community",
    "cat-search-discovery", "cat-products", "cat-privacy-access",
}
COL_RE = re.compile(r'<section\b[^>]*class="tpd-col"[^>]*>.*?</section>', re.S)
HREF_RE = re.compile(r'<h2>\s*<a href="(/category/[^"]+)"[^>]*>(.*?)</a>', re.S)


def link_label(inner: str) -> str:
    text = re.sub(r"<[^>]+>", "", inner)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def columns(html: str):
    start = html.find('class="container tpd-cols')
    if start < 0:
        return None
    start = html.rfind("<div", 0, start)
    found = list(COL_RE.finditer(html, start))
    if not found:
        return None
    end = found[-1].end()
    close = re.match(r"\s*</div>", html[end:])
    if close:
        end += close.end()
    return start, end, found


def index_html(links: list[tuple[str, str]], anchor: str | None) -> str:
    seen = set()
    parts = []
    for href, label in links:
        if href in seen:
            continue
        seen.add(href)
        parts.append(f'<a href="{href}">{label}</a>')
    ident = f' id="{anchor}"' if anchor else ""
    return (
        f'<nav class="tpd-index"{ident} aria-label="All categories">'
        + "".join(parts)
        + "</nav>"
    )


def slim(html: str, home: bool) -> str:
    found = columns(html)
    if not found:
        return html
    start, end, sections = found
    keep, extra = [], []
    for section in sections:
        block = section.group(0)
        ident = re.search(r'id="(cat-[^"]+)"', block)
        slug = ident.group(1) if ident else ""
        heading = HREF_RE.search(block)
        if heading:
            extra.append((heading.group(1), link_label(heading.group(2))))
        if home and slug in KEEP:
            keep.append(block)
    if home:
        body = '<div class="container tpd-cols">' + "".join(keep) + "</div>"
        # Links for categories whose columns were removed. Kept columns already link themselves.
        removed = [(href, label) for href, label in extra if f'href="{href}"' not in "".join(keep)]
        body += index_html(removed, None)
    else:
        body = index_html(extra, "related-categories-1")
    return html[:start] + body + html[end:]


def main() -> None:
    changed = 0
    home = ROOT / "index.html"
    original = home.read_text(encoding="utf-8")
    updated = slim(original, True)
    if updated != original:
        home.write_text(updated, encoding="utf-8")
        changed += 1
        print(f"index.html {len(original)} -> {len(updated)}")
    for path in sorted(ROOT.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix == ".html" and "category" in path.relative_to(ROOT).parts:
            text = path.read_text(encoding="utf-8")
            if "tpd-cols" not in text:
                continue
            new = slim(text, False)
            if new != text:
                path.write_text(new, encoding="utf-8")
                changed += 1
        elif path.suffix == ".json" and "pages" in path.parts and "assets" in path.parts:
            raw = path.read_text(encoding="utf-8")
            if "tpd-cols" not in raw:
                continue
            data = json.loads(raw)
            body = data.get("body") or ""
            new = slim(body, False)
            if new == body:
                continue
            data["body"] = new
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            changed += 1
    print(f"slimmed {changed}")


if __name__ == "__main__":
    main()
