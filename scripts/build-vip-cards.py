#!/usr/bin/env python3
"""Rebuild every .vip-rich card from the linked post's own metadata.

Review cards (single-platform *-review/ posts): letter mark, name, category,
published score or a type badge, excerpt, "Read review →", "Updated Mon YYYY".

Guide cards (lists, alternatives, comparisons, blog posts, topic hubs):
16:10 WebP cover when that post has cover.jpg, pill, H1, excerpt, date,
"View ranking →" or "Read →", and an item count only when the post states one.

Rewrites static HTML, the client-nav JSON copies, and the category guide
renderer in assets/directory-app.js. Does not touch ItemList JSON-LD.
"""
from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
THUMB = ROOT / "assets" / "card-thumbs"
ARTICLE_RE = re.compile(r'<article class="vip-rich(?: [^"]*)?">.*?</article>', re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
SCRIPT_RE = re.compile(r"(<script\b[^>]*>.*?</script>)", re.S | re.I)
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
NUM_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
NOUNS = {
    "site", "sites", "tool", "tools", "app", "apps", "room", "rooms", "hub", "hubs",
    "option", "options", "guide", "guides", "generator", "generators", "alternative",
    "alternatives", "platform", "platforms", "directory", "directories", "writer",
    "writers", "game", "games", "companion", "companions", "pick", "picks", "cam",
    "cams", "list", "lists", "ranked",
}
PALETTE = [
    "#6d28d9", "#db2777", "#e11d48", "#ea580c", "#d97706", "#059669",
    "#0f766e", "#0284c7", "#2563eb", "#4f46e5", "#9333ea", "#be123c",
    "#b45309", "#047857", "#0369a1", "#7c3aed",
]
AI_SLUGS = {
    "ablx-review", "ai-angels-review", "kindroid-review", "ourdream-ai-review",
    "chai-ai-review", "ai-peeps-review", "udesire-ai-review", "spicychat-ai-review",
    "candy-ai-review", "crushon-ai-review", "kalon-ai-review", "dreamgf-ai-review",
    "girlfriendgpt-review", "replika-review", "redquill-review", "aismutwriter-review",
    "smutfinder-review", "novelx-review",
}
FEET_SLUGS = {
    "feetfinder-review", "footly-review", "secretundies-review", "all-things-worn-review",
    "fetishfinder-review", "footlove-review", "fun-with-feet-review", "onlyfeet-review",
    "snifffr-review",
}
CAM_SLUGS = {
    "stripchat-review", "bongacams-review", "camsoda-review", "flirt4free-review",
    "jerkmate-review", "livejasmin-review", "chaturbate-review", "jerkay-review",
}
TUBE_SLUGS = {
    "fapello-review", "fikfap-review", "borntobefuck-review", "hqporner-review", "sxyprn-review",
}
CREATOR_SLUGS = {"onlyfans-review", "fansly-review", "fanvue-review", "patreon-review"}
DATING_SLUGS = {
    "bumble-review", "tinder-review", "adult-friend-finder-review", "ashley-madison-review",
    "seeking-review", "private-sugar-club-review",
}


def esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def norm(href: str) -> str:
    path = re.sub(r"^https?://(?:www\.)?dark-ero\.store", "", href.strip())
    path = path.split("#", 1)[0].split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()


def unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&nbsp;", " ")
    )


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def ld_nodes(html: str) -> list:
    nodes = []
    for match in LD_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            nodes.extend(walk(json.loads(raw)))
        except json.JSONDecodeError:
            continue
    return nodes


def meta_content(html: str, name: str) -> str:
    match = re.search(
        rf'<meta[^>]+name="{name}"[^>]+content="([^"]*)"',
        html,
        re.I,
    )
    if not match:
        match = re.search(
            rf'<meta[^>]+content="([^"]*)"[^>]+name="{name}"',
            html,
            re.I,
        )
    return unescape(match.group(1)).strip() if match else ""


def clean_title(text: str) -> str:
    text = unescape(strip_tags(text))
    text = re.sub(r"\s*\|\s*Dark-Ero\s*$", "", text, flags=re.I).strip()
    return re.sub(r"\s+", " ", text)


def parse_date(value: str | None):
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if not 1 <= month <= 12:
        return None
    return year, month, day


def format_score(raw) -> str | None:
    try:
        number = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 10:
        return None
    return f"{number:.1f}"


def extract_count(*texts: str) -> int | None:
    for text in texts:
        if not text:
            continue
        match = re.search(r"\btop\s+(\d{1,2})\b", text, re.I)
        if match:
            number = int(match.group(1))
            if 2 <= number <= 40:
                return number
        for match in re.finditer(r"\b(\d{1,2})\s+((?:[A-Za-z]+\s+){0,5}[A-Za-z]+)", text):
            number = int(match.group(1))
            words = {word.lower() for word in match.group(2).split()}
            if 2 <= number <= 40 and words & NOUNS:
                return number
        for word, number in NUM_WORDS.items():
            match = re.search(
                rf"\b{word}\b(?:\s+[A-Za-z]+){{0,6}}\s+([A-Za-z]+)",
                text,
                re.I,
            )
            if match and match.group(1).lower() in NOUNS:
                return number
            if re.search(rf"\b{word}\b(?:\s+[A-Za-z]+){{0,6}}\s+ranked\b", text, re.I):
                return number
    return None


def review_category(path: str, section: str, crumbs: list[str]) -> str:
    slug = path.strip("/").split("/")[-1]
    if slug in CREATOR_SLUGS:
        return "Creator platforms"
    if slug in FEET_SLUGS:
        return "Feet marketplaces"
    if slug in CAM_SLUGS:
        return "Live cams"
    if slug in TUBE_SLUGS:
        return "Tube/clip"
    if slug in DATING_SLUGS:
        return "Dating"
    if slug in AI_SLUGS or (section or "").startswith("AI") or (section or "").startswith("NSFW AI"):
        return "AI companions"
    if slug == "spicyranked-review":
        return "Directories"
    if section and section not in {"Reviews", "Blog", "Guides"}:
        return section
    for crumb in crumbs:
        if crumb not in {"Home", "Reviews", "Blog"}:
            return crumb
    return "Review"


def guide_pill(path: str, title: str, section: str) -> str:
    topic = re.search(r"/blog/topic/([a-z0-9-]+)/", path)
    if topic:
        return {
            "ai": "AI",
            "privacy": "Privacy",
            "guides": "Guides",
            "safety": "Safety",
            "creators": "Creators",
            "vr": "VR",
        }.get(topic.group(1), topic.group(1).title())
    if path == "/about/":
        return "About"
    blob = f"{path} {title} {section}".lower()
    if any(key in blob for key in ("privacy", "browser-hygiene", "vpn")):
        return "Privacy"
    if any(key in blob for key in ("dating", "tinder", "bumble", "hinge", "sugar daddy", "sugar-daddy")):
        return "Dating"
    if "escort" in blob:
        return "Escorts"
    if any(key in blob for key in ("feet", "foot", "panties")):
        return "Feet"
    if any(key in blob for key in ("omegle", "chaturbate", "stripchat", "cam site", "cam-site", "cams", "-cam")):
        return "Cam sites"
    if "/vr" in path or "headset" in blob or re.search(r"\bvr\b", blob):
        return "VR"
    if re.search(r"\bgames?\b", blob):
        return "Games"
    if any(key in blob for key in ("onlyfans", "fansly", "fanvue", "patreon", "creator")):
        return "Creators"
    if section in {"AI", "AI girlfriend apps", "AI porn video generators", "AI sex story generators", "AI sexting apps", "AI smut writers", "NSFW AI image generators"} or re.search(r"\bai\b", blob) or any(key in blob for key in ("companion", "smut", "spicychat", "janitor")):
        return "AI"
    if section == "Safety" or any(key in blob for key in ("scam", "malware", "safety")):
        return "Safety"
    if "/comparisons/" in path:
        return "Cam sites"
    if section == "Creators":
        return "Creators"
    if section == "Privacy":
        return "Privacy"
    return "Guides"


def is_ranking(path: str, title: str, count: int | None) -> bool:
    if "/comparisons/" in path or "/blog/topic/" in path or path == "/about/":
        return False
    if "best-" in path or "alternatives" in path:
        return True
    if re.search(r"\b(best|ranked)\b", title, re.I):
        return True
    if count and re.search(r"\b(top\s+\d+|\d+\s+(?:\w+\s+){0,3}(?:apps|sites|tools|platforms))\b", title, re.I):
        return True
    return False


def initials(name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if not parts:
        return "DE"
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    caps = re.findall(r"[A-Z]", parts[0])
    if len(caps) >= 2:
        return caps[0] + caps[1]
    return parts[0][:2].upper()


def mark_color(path: str) -> str:
    digest = hashlib.md5(path.encode()).hexdigest()
    return PALETTE[int(digest[:2], 16) % len(PALETTE)]


def review_name(path: str, reviewed: str, h1: str) -> str:
    if reviewed:
        return re.sub(r"\s+review$", "", reviewed, flags=re.I).strip()
    name = re.split(r"\s+review\b", h1 or "", flags=re.I)[0].strip(" :|-")
    if name:
        return name
    slug = path.strip("/").split("/")[-1].replace("-review", "").replace("-", " ")
    return slug.title()


def load_post(path: str) -> dict | None:
    if path == "/":
        file_path = ROOT / "index.html"
    else:
        file_path = ROOT / path.strip("/") / "index.html"
    if not file_path.exists():
        return None
    html = file_path.read_text(encoding="utf-8")
    nodes = ld_nodes(html)
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    h1 = clean_title(h1_match.group(1) if h1_match else "")
    title = clean_title(re.search(r"<title[^>]*>(.*?)</title>", html, re.S).group(1)) if re.search(r"<title[^>]*>", html) else h1
    description = meta_content(html, "description")
    section = ""
    reviewed = ""
    modified = ""
    published = ""
    score = None
    crumbs = []
    for node in nodes:
        if not section and node.get("articleSection"):
            section = str(node["articleSection"])
        if not reviewed:
            item = node.get("itemReviewed")
            if isinstance(item, dict) and item.get("name"):
                reviewed = str(item["name"])
        if node.get("dateModified") and not modified:
            modified = str(node["dateModified"])
        if node.get("datePublished") and not published:
            published = str(node["datePublished"])
        if score is None and node.get("reviewRating"):
            rating = node["reviewRating"]
            if isinstance(rating, dict) and rating.get("ratingValue"):
                score = format_score(rating.get("ratingValue"))
        if node.get("@type") == "BreadcrumbList":
            for item in node.get("itemListElement") or []:
                if isinstance(item, dict) and item.get("name"):
                    crumbs.append(str(item["name"]))
    kind = "review" if path.rstrip("/").endswith("-review") else "guide"
    when = parse_date(modified or published)
    cover = file_path.parent / "cover.jpg"
    count = extract_count(h1, title, description) if kind == "guide" else None
    ranking = is_ranking(path, f"{h1} {title}", count) if kind == "guide" else False
    if not ranking:
        count = None
    return {
        "path": path,
        "kind": kind,
        "h1": h1,
        "title": title,
        "description": description,
        "section": section,
        "reviewed": reviewed,
        "date": when,
        "score": score if kind == "review" else None,
        "crumbs": crumbs,
        "cover": cover if cover.exists() else None,
        "count": count,
        "ranking": ranking,
        "name": review_name(path, reviewed, h1 or title) if kind == "review" else (h1 or title),
        "category": review_category(path, section, crumbs) if kind == "review" else guide_pill(path, f"{h1} {title}", section),
    }


def thumb_id(path: str) -> str:
    return path.strip("/").replace("/", "-")


def make_thumbs(src: Path, stem: str) -> tuple[int, int]:
    image = Image.open(src).convert("RGB")
    width, height = image.size
    target = 16 / 10
    if width / height > target:
        cropped = int(height * target)
        left = (width - cropped) // 2
        image = image.crop((left, 0, left + cropped, height))
    else:
        cropped = int(width / target)
        top = max(0, (height - cropped) // 2)
        image = image.crop((0, top, width, top + cropped))
    sizes = {}
    for edge in (480, 800):
        frame = image.resize((edge, edge * 10 // 16), Image.Resampling.LANCZOS)
        best = None
        for quality in (68, 60, 52, 44, 38, 32, 28, 24):
            buffer = BytesIO()
            frame.save(buffer, format="WEBP", quality=quality, method=6)
            data = buffer.getvalue()
            best = data
            if len(data) <= 30 * 1024:
                break
        if best is None or len(best) > 30 * 1024:
            raise SystemExit(f"{stem}-{edge}.webp is {len(best) if best else 0} bytes")
        (THUMB / f"{stem}-{edge}.webp").write_bytes(best)
        sizes[edge] = len(best)
    return sizes[480], sizes[800]


def render_card(meta: dict, href: str, image_mode: str) -> str:
    excerpt = meta["description"]
    date = meta["date"]
    if meta["kind"] == "review":
        bits = [
            '<article class="vip-rich vip-review"><a class="vip-card" href="',
            esc(href),
            '"><span class="vip-top"><span class="vip-mark" style="background:',
            mark_color(meta["path"]),
            '" aria-hidden="true">',
            esc(initials(meta["name"])),
            '</span><span class="vip-id"><h3>',
            esc(meta["name"]),
            '</h3><span class="vip-cat">',
            esc(meta["category"]),
            "</span></span>",
        ]
        if meta["score"]:
            bits.append(f'<span class="vip-score">{esc(meta["score"])}</span>')
        else:
            bits.append('<span class="vip-badge">Review</span>')
        bits.append("</span>")
        if excerpt:
            bits.append(f"<p>{esc(excerpt)}</p>")
        bits.append('<span class="vip-foot"><span class="vip-cta">Read review →</span>')
        if date:
            bits.append(f'<span class="vip-date">Updated {MONTHS[date[1] - 1]} {date[0]}</span>')
        bits.append("</span></a></article>")
        return "".join(bits)

    bits = ['<article class="vip-rich vip-guide"><a class="vip-card" href="', esc(href), '">']
    if meta.get("thumb") and image_mode:
        stem = meta["thumb"]
        src480 = f"/assets/card-thumbs/{stem}-480.webp"
        src800 = f"/assets/card-thumbs/{stem}-800.webp"
        loading = ' loading="lazy"'
        priority = ""
        if image_mode == "high":
            loading = ' loading="eager"'
            priority = ' fetchpriority="high"'
        elif image_mode == "low":
            loading = ' loading="eager"'
            priority = ' fetchpriority="low"'
        bits.append(
            '<span class="vip-cover"><img src="'
            + src480
            + '" srcset="'
            + src480
            + " 480w, "
            + src800
            + ' 800w" sizes="(max-width:640px) 92vw, (max-width:960px) 46vw, 340px" width="800" height="500" alt="" decoding="async"'
            + priority
            + loading
            + "></span>"
        )
    bits.append('<span class="vip-body"><span class="vip-kicker"><span class="vip-pill">')
    bits.append(esc(meta["category"]))
    bits.append("</span>")
    if meta.get("count"):
        bits.append(f'<span class="vip-count">{meta["count"]} ranked</span>')
    bits.append("</span><h3>")
    bits.append(esc(meta["name"]))
    bits.append("</h3>")
    if excerpt:
        bits.append(f"<p>{esc(excerpt)}</p>")
    cta = "View ranking →" if meta["ranking"] else "Read →"
    bits.append('<span class="vip-foot">')
    if date:
        bits.append(f'<span class="vip-date">{MONTHS[date[1] - 1]} {date[2]}, {date[0]}</span>')
    bits.append(f'<span class="vip-cta">{cta}</span></span></span></a></article>')
    return "".join(bits)


def replace_outside_scripts(html: str, cards_for) -> tuple[str, int]:
    parts = SCRIPT_RE.split(html)
    count = 0

    def repl_card(match: re.Match, state: dict) -> str:
        nonlocal count
        old = match.group(0)
        href_match = HREF_RE.search(old)
        if not href_match:
            return old
        href = href_match.group(1)
        meta = cards_for(norm(href))
        if meta is None:
            return old
        mode = ""
        if state["eager"] and meta["kind"] == "guide" and meta.get("thumb"):
            state["n"] += 1
            # The first cover is the likely LCP image. The next two sit in the
            # desktop first row, so they stay eager but low priority. Everything
            # past that row is below the fold.
            if state["n"] == 1:
                mode = "high"
            elif state["n"] <= 3:
                mode = "low"
            else:
                mode = "lazy"
        elif meta["kind"] == "guide" and meta.get("thumb"):
            mode = "lazy"
        count += 1
        return render_card(meta, href, mode)

    def repl_part(part: str) -> str:
        chunks = re.split(r'(<div class="vip-grid">)', part)
        out = []
        grid = 0
        index = 0
        while index < len(chunks):
            if chunks[index] == '<div class="vip-grid">':
                grid += 1
                out.append(chunks[index])
                index += 1
                if index >= len(chunks):
                    break
                state = {"n": 0, "eager": grid == 1}
                out.append(ARTICLE_RE.sub(lambda match: repl_card(match, state), chunks[index]))
            else:
                state = {"n": 0, "eager": False}
                out.append(ARTICLE_RE.sub(lambda match: repl_card(match, state), chunks[index]))
            index += 1
        return "".join(out)

    rebuilt = []
    for index, part in enumerate(parts):
        rebuilt.append(part if index % 2 == 1 else repl_part(part))
    return "".join(rebuilt), count


def ld_blob(html: str) -> str:
    return "\n".join(match.group(0) for match in LD_RE.finditer(html))


def guide_urls_from_js(text: str) -> list[str]:
    start = text.find("var CATEGORY_GUIDES=")
    end = text.find("function categoryGuidesHtml", start)
    if start < 0 or end < 0:
        raise SystemExit("CATEGORY_GUIDES not found")
    return re.findall(r'url:"([^"]+)"', text[start:end])


def patch_directory_app(cards: dict[str, str]) -> None:
    path = ROOT / "assets" / "directory-app.js"
    text = path.read_text(encoding="utf-8")
    urls = guide_urls_from_js(text)
    payload = {url: cards[url] for url in urls if url in cards}
    missing = [url for url in urls if url not in cards]
    if missing:
        raise SystemExit(f"directory cards missing meta: {missing}")
    blob = "var VIP_CARD=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    function = """function categoryGuidesHtml(slug){
  var list=CATEGORY_GUIDES[slug];
  if(!list||!list.length)return "";
  var cards="",eager=0;
  for(var i=0;i<list.length;i++){
    var g=list[i];
    var html=VIP_CARD[g.url];
    if(!html)html='<article class="vip-rich"><h3><a href="'+escHtml(g.url)+'">'+escHtml(g.title)+'</a></h3></article>';
    else if(eager<3 && html.indexOf("vip-cover")!==-1){
      html=html.replace(' loading="lazy"',' loading="eager"'+(eager?' fetchpriority="low"':' fetchpriority="high"'));
      eager++;
    }
    cards+=html;
  }
  return '<section class="vip-guides cat-guides" aria-labelledby="cat-guides-'+slug+'"><div class="section-head"><h2 id="cat-guides-'+slug+'">Guides</h2></div><div class="vip-grid">'+cards+'</div></section>';
}"""
    start = text.find("function categoryGuidesHtml(slug){")
    if start < 0:
        raise SystemExit("categoryGuidesHtml missing")
    end = text.find("\nfunction withCategoryGuides", start)
    if end < 0:
        raise SystemExit("withCategoryGuides missing")
    text = text[:start] + function + "\n" + text[end:]
    if "var VIP_CARD=" in text:
        text = re.sub(r"var VIP_CARD=.*?;\n", "", text, count=1)
    marker = "function categoryGuidesHtml(slug){"
    text = text.replace(marker, blob + marker, 1)
    path.write_text(text, encoding="utf-8")
    print(f"directory-app.js cards {len(payload)}")


def main() -> None:
    html_files = []
    json_files = []
    referenced: set[str] = set()
    for path in sorted(ROOT.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix == ".html" and "vip-rich" in path.read_text(encoding="utf-8"):
            html_files.append(path)
        elif path.suffix == ".json" and "assets" in path.parts and "vip-rich" in path.read_text(encoding="utf-8"):
            json_files.append(path)
    for path in html_files:
        text = path.read_text(encoding="utf-8")
        for match in ARTICLE_RE.finditer(text):
            href = HREF_RE.search(match.group(0))
            if href:
                referenced.add(norm(href.group(1)))
    for path in json_files:
        body = json.loads(path.read_text(encoding="utf-8")).get("body", "")
        for match in ARTICLE_RE.finditer(body):
            href = HREF_RE.search(match.group(0))
            if href:
                referenced.add(norm(href.group(1)))
    js_text = (ROOT / "assets" / "directory-app.js").read_text(encoding="utf-8")
    referenced.update(guide_urls_from_js(js_text))

    posts = {}
    missing_posts = []
    for path in sorted(referenced):
        meta = load_post(path)
        if meta is None:
            missing_posts.append(path)
            continue
        posts[path] = meta
    if missing_posts:
        raise SystemExit("missing posts: " + ", ".join(missing_posts))

    THUMB.mkdir(parents=True, exist_ok=True)
    no_cover = []
    thumb_bytes = []
    for path, meta in posts.items():
        if meta["kind"] != "guide":
            continue
        if not meta["cover"]:
            no_cover.append(path)
            continue
        stem = thumb_id(path)
        small, large = make_thumbs(meta["cover"], stem)
        meta["thumb"] = stem
        thumb_bytes.append((stem, small, large))
    print(f"thumbs {len(thumb_bytes)} max480 {max(s for _, s, _ in thumb_bytes)} max800 {max(l for _, _, l in thumb_bytes)}")

    lazy_cards = {path: render_card(meta, path, "lazy" if meta.get("thumb") else "") for path, meta in posts.items()}

    changed_pages = 0
    changed_cards = 0
    for path in html_files:
        original = path.read_text(encoding="utf-8")
        before_ld = ld_blob(original)
        before_count = len(ARTICLE_RE.findall(original))
        updated, count = replace_outside_scripts(original, posts.get)
        if ld_blob(updated) != before_ld:
            raise SystemExit(f"JSON-LD changed in {path}")
        if count != before_count:
            raise SystemExit(f"card count {before_count} -> {count} in {path}")
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_pages += 1
            changed_cards += count
    json_pages = 0
    for path in json_files:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        body = data.get("body", "")
        before_count = len(ARTICLE_RE.findall(body))
        updated, count = replace_outside_scripts(body, posts.get)
        if count != before_count:
            raise SystemExit(f"json card count changed in {path}")
        if updated == body:
            continue
        # Swap each card in the raw JSON so the rest of the file stays put.
        cursor = 0
        old_cards = ARTICLE_RE.findall(body)
        new_cards = ARTICLE_RE.findall(updated)
        if len(old_cards) != len(new_cards):
            raise SystemExit(f"json card mismatch {path}")
        rebuilt = raw
        for old, new in zip(old_cards, new_cards):
            old_esc = json.dumps(old, ensure_ascii=False)[1:-1]
            new_esc = json.dumps(new, ensure_ascii=False)[1:-1]
            idx = rebuilt.find(old_esc)
            if idx < 0:
                data["body"] = updated
                rebuilt = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                break
            rebuilt = rebuilt[:idx] + new_esc + rebuilt[idx + len(old_esc):]
        else:
            json.loads(rebuilt)
        path.write_text(rebuilt, encoding="utf-8")
        json_pages += 1
        changed_cards += count

    patch_directory_app(lazy_cards)

    no_score = sorted(path for path, meta in posts.items() if meta["kind"] == "review" and not meta["score"])
    no_excerpt = sorted(path for path, meta in posts.items() if not meta["description"])
    no_date = sorted(path for path, meta in posts.items() if not meta["date"])
    excerpts: dict[str, list[str]] = {}
    for path, meta in posts.items():
        excerpts.setdefault(meta["description"], []).append(path)
    dupes = {text: paths for text, paths in excerpts.items() if text and len(paths) > 1}
    print(f"html pages {changed_pages} json copies {json_pages} card writes {changed_cards}")
    print(f"unique posts {len(posts)} reviews {sum(m['kind']=='review' for m in posts.values())} guides {sum(m['kind']=='guide' for m in posts.values())}")
    print("NO SCORE", no_score)
    print("NO COVER", no_cover)
    print("NO EXCERPT", no_excerpt)
    print("NO DATE", no_date)
    print("DUPLICATE EXCERPTS", len(dupes))
    for text, paths in list(dupes.items())[:8]:
        print(" DUP", paths, text[:80])
    print("--- sample ---")
    for path in ("/stripchat-review/", "/footly-review/", "/fikfap-review/", "/blog/best-dating-apps/", "/best-ai-girlfriend-apps/", "/sugar-daddy-apps/", "/comparisons/chaturbate-vs-stripchat/", "/blog/topic/ai/", "/about/"):
        meta = posts[path]
        print(path, meta["kind"], meta["name"][:40], "|", meta["category"], "|", meta["score"], meta["count"], meta["ranking"], "thumb" if meta.get("thumb") else "noimg")


if __name__ == "__main__":
    main()
