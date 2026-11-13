#!/usr/bin/env python3
"""Check every blog, guide, list, alternatives, comparison and review post.

Reads sitemap.xml and skips hubs, categories and legal pages. For each post:
  (a) the article body has exactly one image, the Dark-Ero cover, and no
      mid-article figure;
  (b) cover.jpg is 1200x630, and a responsive WebP hero is 1200:630 too;
  (c) og:image points at that cover;
  (d) every image src and srcset URL exists;
  (e) the canonical is the www URL with a trailing slash.

Exit status is 1 when any post fails.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://www.dark-ero.store"
HUBS = {
    "",
    "about",
    "alternatives",
    "best-lists",
    "blog",
    "categories",
    "comparisons",
    "contact",
    "reviews",
    "submit",
}
LEGAL = {"dmca", "legal-2257", "privacy", "terms"}
GUIDES = {
    "how-to-make-money-selling-feet-pics",
    "how-to-sell-feet-pics-without-getting-scammed",
    "sell-feet-pics",
    "sites-like-onlyfans",
    "sugar-daddy-apps",
    "where-to-sell-feet-pics-for-free",
}
HEADER_RE = re.compile(r"<header\b.*?</header>", re.S)
FOOTER_RE = re.compile(r"<footer\b.*?</footer>", re.S)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
SRC_RE = re.compile(r"""\bsrc=["']([^"']+)["']""", re.I)
SRCSET_RE = re.compile(r"""\bsrcset=["']([^"']+)["']""", re.I)
FIG_RE = re.compile(r'<figure\b([^>]*)>', re.I)
CANON_RE = re.compile(r'<link\b[^>]*rel=["\']canonical["\'][^>]*>', re.I)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
OG_RE = re.compile(
    r'<meta\b[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
OG_RE_ALT = re.compile(
    r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
    re.I,
)


def sitemap_paths() -> list[str]:
    text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", text)
    found = []
    for loc in locs:
        path = urlparse(loc).path
        if not path.endswith("/"):
            path += "/"
        found.append(path)
    return found


def is_post(path: str) -> bool:
    slug = path.strip("/")
    if slug in HUBS or slug in LEGAL or slug.startswith("category/"):
        return False
    if slug.startswith("blog/topic/"):
        return False
    if slug.endswith("-review"):
        return True
    if slug.startswith("blog/"):
        return True
    if slug.startswith("comparisons/"):
        return True
    if slug.startswith("best-") or "alternative" in slug:
        return True
    return slug in GUIDES


def page_file(path: str) -> Path:
    return ROOT / path.strip("/") / "index.html"


def body_html(text: str) -> str:
    text = HEADER_RE.sub("", text)
    return FOOTER_RE.sub("", text)


def cover_src(path: str, src: str) -> bool:
    src = src.split("?")[0]
    slug = path.strip("/").replace("/", "-")
    allowed = {
        "cover.jpg",
        f"{path}cover.jpg",
        f"/assets/card-thumbs/{slug}-480.webp",
        f"/assets/card-thumbs/{slug}-800.webp",
    }
    return src in allowed


def resolve_src(path: str, src: str) -> Path | None:
    src = unquote(src.split("?")[0])
    if src.startswith(("http://", "https://", "data:")):
        return None
    if src.startswith("/"):
        return ROOT / src.lstrip("/")
    return page_file(path).parent / src


def image_urls(tag: str) -> list[str]:
    found = SRC_RE.findall(tag)
    for srcset in SRCSET_RE.findall(tag):
        for part in srcset.split(","):
            url = part.strip().split(" ")[0]
            if url:
                found.append(url)
    return found


def check(path: str) -> list[str]:
    failures = []
    html_path = page_file(path)
    if not html_path.is_file():
        return ["missing page"]
    text = html_path.read_text(encoding="utf-8")
    body = body_html(text)
    tags = IMG_RE.findall(body)
    srcs = []
    for tag in tags:
        srcs.extend(SRC_RE.findall(tag))
    if len(tags) != 1:
        failures.append(f"body images {len(tags)}: {srcs}")
    elif not cover_src(path, srcs[0]):
        failures.append(f"body image is not the cover: {srcs[0]}")
    figures = FIG_RE.findall(body)
    extra = [attrs for attrs in figures if "cover" not in attrs]
    if extra:
        failures.append(f"mid-article figure: {extra}")
    if "assets/media/" in body or 'class="ig"' in body or 'class="vip-steps"' in body:
        failures.append("old photo or mid-article figure markup")

    cover = html_path.parent / "cover.jpg"
    if not cover.is_file():
        failures.append("cover.jpg missing")
    else:
        size = Image.open(cover).size
        if size != (1200, 630):
            failures.append(f"cover.jpg is {size[0]}x{size[1]}")
    for edge, width, height in ((480, 480, 252), (800, 800, 420)):
        thumb = ROOT / "assets" / "card-thumbs" / f"{path.strip('/').replace('/', '-')}-{edge}.webp"
        if any(thumb.name in src for src in srcs):
            if not thumb.is_file():
                failures.append(f"missing {thumb.name}")
            elif Image.open(thumb).size != (width, height):
                failures.append(f"{thumb.name} is {Image.open(thumb).size}")

    expected = f"{ORIGIN}{path}cover.jpg"
    og = OG_RE.search(text) or OG_RE_ALT.search(text)
    if not og:
        failures.append("og:image missing")
    elif og.group(1) != expected:
        failures.append(f"og:image {og.group(1)}")

    for tag in IMG_RE.findall(text):
        for src in image_urls(tag):
            local = resolve_src(path, src)
            if local is None:
                continue
            if not local.is_file():
                failures.append(f"broken image {src}")

    canon = CANON_RE.search(text)
    href = HREF_RE.search(canon.group(0)).group(1) if canon else ""
    want = f"{ORIGIN}{path}"
    if href != want:
        failures.append(f"canonical {href or 'missing'}")
    return failures


def main() -> None:
    posts = [path for path in sitemap_paths() if is_post(path)]
    failed = []
    for path in posts:
        problems = check(path)
        if problems:
            failed.append((path, problems))
    print(f"checked {len(posts)}")
    print(f"passed {len(posts) - len(failed)}")
    print(f"failed {len(failed)}")
    for path, problems in failed:
        print(path)
        for problem in problems:
            print(f"  - {problem}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
