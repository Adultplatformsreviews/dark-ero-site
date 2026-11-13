#!/usr/bin/env python3
"""Save a 96x96 WebP icon for each review from the site's own domain.

Looks for an apple-touch icon, a favicon, then an og:image. Writes
assets/logos/<review-slug>.webp under 5 KB. Prints slugs that stay
on the letter-mark fallback.
"""
from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "logos"
UA = "Mozilla/5.0 (compatible; DarkEroLogoBot/1.0; +https://www.dark-ero.store/)"

# Official host for each review. Directory hosts win when the review names one;
# the rest are the site's own public domain.
DOMAINS = {
    "ablx-review": "ablx.app",
    "adult-friend-finder-review": "adultfriendfinder.com",
    "ai-angels-review": "aiangels.io",
    "ai-peeps-review": "aipeeps.com",
    "aismutwriter-review": "aismutwriter.com",
    "all-things-worn-review": "allthingsworn.com",
    "ashley-madison-review": "ashleymadison.com",
    "bongacams-review": "bongacams.com",
    "borntobefuck-review": "borntobefuck.com",
    "bumble-review": "bumble.com",
    "camsoda-review": "camsoda.com",
    "candy-ai-review": "candy.ai",
    "chai-ai-review": "chai.ml",
    "chaturbate-review": "chaturbate.com",
    "crushon-ai-review": "crushon.ai",
    "dreamgf-ai-review": "dreamgf.ai",
    "fansly-review": "fansly.com",
    "fanvue-review": "fanvue.com",
    "fapello-review": "fapello.com",
    "feetfinder-review": "feetfinder.com",
    "fetishfinder-review": "fetishfinder.com",
    "fikfap-review": "fikfap.com",
    "flirt4free-review": "flirt4free.com",
    "footlove-review": "footlove.com",
    "footly-review": "tryfootly.com",
    "fun-with-feet-review": "funwithfeet.net",
    "girlfriendgpt-review": "girlfriendgpt.com",
    "hqporner-review": "hqporner.com",
    "jerkay-review": "jerkay.com",
    "jerkmate-review": "jerkmate.com",
    "kalon-ai-review": "kalon.ai",
    "kindroid-review": "kindroid.ai",
    "livejasmin-review": "livejasmin.com",
    "novelx-review": "novelx.ai",
    "onlyfans-review": "onlyfans.com",
    "onlyfeet-review": "onlyfeet.com",
    "ourdream-ai-review": "ourdream.ai",
    "patreon-review": "patreon.com",
    "private-sugar-club-review": "privatesugarclub.com",
    "redquill-review": "redquill.net",
    "replika-review": "replika.com",
    "secretundies-review": "secretundies.com",
    "seeking-review": "seeking.com",
    "smutfinder-review": "smutfinder.com",
    "snifffr-review": "snifffr.com",
    "spicychat-ai-review": "spicychat.ai",
    "spicyranked-review": "spicyranked.com",
    "stripchat-review": "stripchat.com",
    "sxyprn-review": "sxyprn.com",
    "tinder-review": "tinder.com",
    "udesire-ai-review": "udesire.ai",
}


def fetch(url: str, limit: int = 1_500_000) -> bytes:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,image/*,*/*"})
    with urlopen(req, timeout=12) as response:
        return response.read(limit)


def candidates(domain: str) -> list[str]:
    page = f"https://{domain}/"
    ordered: list[str] = []
    try:
        html = fetch(page, 400_000).decode("utf-8", "replace")
    except Exception:
        html = ""
    tags = re.findall(r"<link\b[^>]*>", html, re.I)
    apple, icons = [], []
    for tag in tags:
        rel = " ".join(re.findall(r'rel=["\']([^"\']+)', tag, re.I)).lower()
        href_m = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if not href_m or href_m.group(1).startswith("data:"):
            continue
        href = urljoin(page, href_m.group(1))
        if "apple-touch" in rel:
            apple.append(href)
        elif "icon" in rel:
            icons.append(href)
    ordered.extend(apple)
    ordered.extend(icons)
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if not og:
        og = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    if og and not og.group(1).startswith("data:"):
        ordered.append(urljoin(page, og.group(1)))
    ordered.append(f"https://{domain}/apple-touch-icon.png")
    ordered.append(f"https://{domain}/favicon.ico")
    seen, unique = set(), []
    for url in ordered:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def to_webp(raw: bytes) -> bytes | None:
    try:
        image = Image.open(io.BytesIO(raw))
        image.seek(0)
    except Exception:
        return None
    if max(image.size) < 16:
        return None
    image = image.convert("RGBA")
    width, height = image.size
    if width / height > 2.2 or height / width > 2.2:
        return None
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    background = Image.new("RGB", (side, side), (255, 255, 255))
    background.paste(image, mask=image.split()[-1])
    background = background.resize((96, 96), Image.Resampling.LANCZOS)
    best = None
    for quality in (80, 68, 56, 44, 34, 26, 18):
        buffer = io.BytesIO()
        background.save(buffer, format="WEBP", quality=quality, method=6)
        data = buffer.getvalue()
        best = data
        if len(data) <= 5 * 1024:
            return data
    return best if best and len(best) <= 5 * 1024 else None


def one(slug: str, domain: str) -> tuple[str, str]:
    for url in candidates(domain):
        try:
            raw = fetch(url)
        except Exception:
            continue
        webp = to_webp(raw)
        if not webp:
            continue
        (OUT / f"{slug}.webp").write_bytes(webp)
        return slug, f"ok {domain} {len(webp)} {url[:80]}"
    return slug, f"FAIL {domain}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one, slug, domain) for slug, domain in sorted(DOMAINS.items())]
        for future in as_completed(futures):
            slug, message = future.result()
            print(message, slug)
            if message.startswith("FAIL"):
                failed.append(slug)
    print("FAILED", len(failed))
    for slug in sorted(failed):
        print(" ", slug)


if __name__ == "__main__":
    main()
