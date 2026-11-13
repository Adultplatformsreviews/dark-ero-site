#!/usr/bin/env python3
"""Save a sharp square WebP icon for each review from the site's own domain.

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
    "footly-review": "tryfootly.org",
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


def largest_frame(image: Image.Image) -> Image.Image:
    best = image.copy()
    frames = getattr(image, "n_frames", 1)
    for index in range(frames):
        image.seek(index)
        if max(image.size) > max(best.size):
            best = image.copy()
    return best


def to_webp(raw: bytes) -> tuple[bytes, int] | None:
    try:
        image = largest_frame(Image.open(io.BytesIO(raw)))
        image.load()
    except Exception:
        return None
    if max(image.size) < 16:
        return None
    image = image.convert("RGBA")
    width, height = image.size
    ratio = width / height
    # Share cards and banners are not logos. Keep nearly square marks only.
    if ratio > 1.25 or ratio < 0.8:
        return None
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    background = Image.new("RGB", (side, side), (255, 255, 255))
    background.paste(image, mask=image.split()[-1])
    # A 3x phone needs about 180px for the mark inside the circle. Do not invent detail past 96.
    target = min(256, side if side >= 96 else 96)
    if target != side:
        background = background.resize((target, target), Image.Resampling.LANCZOS)
    best = None
    for quality in (82, 74, 66, 56, 46):
        buffer = io.BytesIO()
        background.save(buffer, format="WEBP", quality=quality, method=6)
        data = buffer.getvalue()
        best = data
        if len(data) <= 12 * 1024:
            return data, side
    if best and len(best) <= 18 * 1024:
        return best, side
    return None


def one(slug: str, domain: str) -> tuple[str, str]:
    best = None
    best_side = 0
    best_url = ""
    for url in candidates(domain):
        try:
            raw = fetch(url)
            image = Image.open(io.BytesIO(raw))
            image.seek(0)
        except Exception:
            continue
        if min(image.size) < 16:
            continue
        converted = to_webp(raw)
        if not converted:
            continue
        webp, side = converted
        if side < best_side:
            continue
        best, best_side, best_url = webp, side, url
    if not best:
        return slug, f"FAIL {domain}"
    (OUT / f"{slug}.webp").write_bytes(best)
    return slug, f"ok {domain} {best_side}px {len(best)} {best_url[:80]}"


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
