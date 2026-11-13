#!/usr/bin/env python3
"""Render Dark-Ero guide covers with headless Chromium.

Layout follows the SpicyRanked cover structure (kicker, accent title, chips,
right-hand card, brand bar). Colors and the logo are Dark-Ero's. Every
figure and checklist line is taken from that post.
"""
from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FONT_URI = "data:font/woff2;base64," + base64.b64encode(
    (ROOT / "assets" / "fonts" / "bricolage-grotesque-latin.woff2").read_bytes()
).decode("ascii")
LOGO = (ROOT / "assets" / "logo.svg").read_text(encoding="utf-8")
LOGO = re.sub(r"<\?xml[^>]*>", "", LOGO)
LOGO = re.sub(r'width="64"', 'width="36"', LOGO)
LOGO = re.sub(r'height="64"', 'height="36"', LOGO)
SAMPLES = [
    "how-to-sell-feet-pics-uk",
    "how-to-take-feet-pics",
    "how-to-get-unbanned-from-omegle",
    "best-ai-girlfriend-apps",
    "onlyfans-top-earners",
    "best-free-cam-sites",
]
SKIP_H2 = {
    "at a glance", "key takeaways", "faq", "verdict", "contents",
    "related reading", "related categories", "table of contents",
}
STOP = {
    "how", "to", "a", "an", "the", "in", "of", "for", "and", "your", "from",
    "with", "what", "is", "are", "on", "2026", "guide", "best", "you", "it",
    "its", "this", "that", "when", "without", "into", "vs", "get", "make",
    "sell", "take", "keep", "see", "read", "use", "do", "does", "can", "may",
}
DANGLING = {
    "before", "of", "in", "to", "a", "an", "the", "just", "for", "and", "on",
    "with", "that", "up", "by", "or", "as", "at", "from", "because", "which",
    "while", "than", "about", "after", "into", "over", "who", "whose", "were",
    "was", "their", "your", "you", "its", "if", "when", "how", "what", "all",
    "showed", "covers", "near", "then", "ranked",
}
MONEY = re.compile(
    r"(?:£|\$|€)\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s?(?:million|billion))?"
    r"|\b\d{1,3}(?:\.\d+)?\s?(?:%|percent)\b",
    re.I,
)
DATE = re.compile(
    r"\b\d{1,2}\s(?:January|February|March|April|May|June|July|August|September|October|November|December)\s20\d{2}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s\d{1,2},?\s20\d{2}\b"
    r"|\b\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s20\d{2}\b",
    re.I,
)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def last_word(text: str) -> str:
    parts = text.split()
    if not parts:
        return ""
    return re.sub(r"[^A-Za-z]", "", parts[-1]).lower()


def cut_off(text: str) -> bool:
    return last_word(text) in DANGLING


def fit(text: str, limit: int) -> str:
    """Shorten on a word boundary. No ellipsis. Drop a trailing preposition only after a cut."""
    text = clean(text).rstrip(".!?")
    if len(text) <= limit:
        return text
    words = text.split()
    while words and len(" ".join(words)) > limit:
        words.pop()
    while len(words) > 4 and cut_off(" ".join(words)):
        words.pop()
    return " ".join(words).rstrip(".,;:").strip()


def one_line(text: str, limit: int = 70) -> str:
    text = clean(text)
    first = re.split(r"(?<=[.!?])\s", text)[0].strip().rstrip(".!?")
    if len(first) <= limit:
        return first
    return fit(first, limit)


def targets() -> list[Path]:
    found = []
    hubs = {"blog", "comparisons", "best-lists", "alternatives", "reviews", "category"}
    for path in sorted(ROOT.rglob("index.html")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        if "assets" in path.parts:
            continue
        parent = path.parent
        if "category" in path.relative_to(ROOT).parts:
            continue
        if parent == ROOT or parent.name in hubs and parent.parent == ROOT:
            continue
        if parent.name.endswith("-review"):
            continue
        rel = parent.relative_to(ROOT).as_posix()
        name = parent.name
        if (
            rel.startswith("blog/")
            or rel.startswith("comparisons/")
            or rel in {
                "about",
                "sell-feet-pics",
                "sites-like-onlyfans",
                "sugar-daddy-apps",
                "where-to-sell-feet-pics-for-free",
                "how-to-make-money-selling-feet-pics",
                "how-to-sell-feet-pics-without-getting-scammed",
            }
            or name.startswith("best-")
            or "alternatives" in name
        ):
            found.append(path)
    return found


def meta_desc(text: str) -> str:
    match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', text, re.I)
    if not match:
        match = re.search(r'<meta[^>]+content="([^"]*)"[^>]+name="description"', text, re.I)
    return clean(match.group(1)) if match else ""


def field(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.S | re.I)
    return clean(match.group(1)) if match else ""


def lede_of(text: str) -> str:
    match = re.search(r'<p class="lede">(.*?)</p>', text, re.S)
    return clean(match.group(1)) if match else ""


def takeaways(text: str) -> list[str]:
    block = re.search(r'<section class="takeaways".*?</section>', text, re.S)
    if not block:
        return []
    items = [clean(item) for item in re.findall(r"<li>(.*?)</li>", block.group(0), re.S)]
    return [item for item in items if item and "spicyranked" not in item.lower()]


def glances(text: str) -> list[str]:
    rows = re.findall(r'<p class="g-row[^"]*">(.*?)</p>', text, re.S)
    return [clean(row) for row in rows if "spicyranked" not in clean(row).lower()]


def headings(text: str) -> list[str]:
    found = []
    for raw in re.findall(r"<h2[^>]*>(.*?)</h2>", text, re.S):
        title = clean(raw)
        if title.lower() in SKIP_H2 or len(title) < 3:
            continue
        if "spicyranked" in title.lower():
            continue
        found.append(title)
    return found[:4]


def feetish(slug: str, title: str) -> bool:
    blob = f"{slug} {title}".lower()
    return any(word in blob for word in ("feet", "foot", "panty", "panties", "fetishfinder"))


def kicker_for(path: Path, title: str) -> str:
    slug = path.parent.name
    rel = path.parent.relative_to(ROOT).as_posix()
    if "uk" in slug and feetish(slug, title):
        label = "UK seller guide"
    elif feetish(slug, title):
        label = "Feet guide"
    elif re.search(r"(^|-)(omegle|cams?)(-|$)", slug):
        label = "Cam sites"
    elif rel.startswith("blog/topic/privacy") or re.search(r"(^|-)(privacy|vpn|browser)(-|$)", slug):
        label = "Privacy"
    elif re.search(r"(^|-)(safety|scams?|malware|leaks?)(-|$)", slug):
        label = "Safety"
    elif "alternatives" in slug:
        label = "Alternatives"
    elif slug.startswith("best-") or rel.startswith("best-"):
        label = "Best list"
    elif rel.startswith("comparisons/"):
        label = "Comparison"
    elif any(word in slug for word in ("onlyfans", "fansly", "fanvue", "creator", "earn")):
        label = "Creator guide"
    elif slug.startswith("ai") or "-ai" in slug or "ai-" in slug or "companion" in slug:
        label = "AI guide"
    elif rel.startswith("blog/topic/"):
        label = {"ai": "AI", "vr": "VR"}.get(path.parent.name, path.parent.name.replace("-", " ").title())
    elif rel == "about":
        label = "About"
    else:
        label = "Guide"
    return f"{label} · 2026"


def accent_title(title: str) -> str:
    words = title.split()
    chosen = []
    for word in words:
        bare = re.sub(r"[^A-Za-z0-9£$%]", "", word).lower()
        if bare in STOP or len(bare) < 3:
            continue
        chosen.append(word)
        if len(chosen) == 2:
            break
    if not chosen and words:
        chosen = [words[-1]]
    html_words = []
    for word in words:
        if word in chosen:
            html_words.append(f"<em>{esc(word)}</em>")
            chosen.remove(word)
        else:
            html_words.append(esc(word))
    return " ".join(html_words)


# Complete 1–3 word labels. A label is used only when the post itself says so.
LABEL_RULES = [
    (r"\bhmrc\b", "HMRC tax"),
    (r"\ballowance\b", "Trading allowance"),
    (r"\banonym", "Stay anonymous"),
    (r"\b18\b", "Legal 18+"),
    (r"£", "Priced in £"),
    (r"\$", "Priced in $"),
    (r"\brefund", "Refund rules"),
    (r"\bverif|\bid check|\bgovernment id\b", "ID check"),
    (r"\b80\s*(?:%|percent)", "80% kept"),
    (r"\b20\s*(?:%|percent)", "20% fee"),
    (r"\bvpn\b", "VPN limits"),
    (r"\bscam", "Scam checks"),
    (r"\bwatermark", "Watermark previews"),
    (r"\bclosed\b|\bshut down\b|\bhas not returned\b", "Site closed"),
    (r"\bmemory\b", "Memory ranked"),
    (r"\bfree\b", "Free tier"),
    (r"\bprivate show|\bprivate\b", "Private shows"),
    (r"\btoken", "Token prices"),
    (r"\bpayout", "Payout rules"),
    (r"\bself assessment\b|\bregister\b", "Register income"),
    (r"\bphone\b", "Phone is enough"),
    (r"\bapk\b|\bunban app", "No unban apps"),
    (r"\bleak", "Leak risk"),
    (r"\bconsent\b", "Consent rules"),
    (r"\bage\b", "Age checked"),
]


def chips_for(text: str) -> list[str]:
    blob = clean(" ".join(glances(text) + takeaways(text) + [lede_of(text), meta_desc(text), field(text, "h1")]))
    seen, out = set(), []
    for pattern, label in LABEL_RULES:
        if not re.search(pattern, blob, re.I):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
        if len(out) == 4:
            break
    if len(out) < 3:
        for head in headings(text):
            words = [word for word in re.findall(r"[A-Za-z0-9+£$%]+", head) if word.lower() not in STOP]
            if not words:
                continue
            label = " ".join(words[:3])
            if label.lower() in seen or len(label) < 3:
                continue
            seen.add(label.lower())
            out.append(label)
            if len(out) == 4:
                break
    return out[:4]


def sentence_with(blob: str, match: re.Match) -> str:
    start = blob.rfind(".", 0, match.start())
    end = blob.find(".", match.end())
    if end < 0:
        end = len(blob)
    return blob[start + 1:end].strip()


WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "thirteen": "13", "fourteen": "14", "fifteen": "15", "twenty": "20",
}


def caption_beside(sentence: str, number: str) -> str:
    index = sentence.find(number)
    if index < 0:
        return fit(sentence, 52)
    after = sentence[index + len(number):].strip(" .,;")
    before = sentence[:index].strip(" .,;")
    before_l = before.lower()
    if any(word in before_l for word in ("allowance", "plan", "fee", "gross", "closed", "keeps")):
        source = before
    else:
        source = after if len(after) >= 12 else before
    words = source.split()[:8]
    while words and words[0].lower().strip(",;") in {"of", "a", "the", "so", "and", "near"}:
        words.pop(0)
    while words and words[-1].lower().strip(",;") in DANGLING:
        words.pop()
    return fit(" ".join(words), 52)


def fact_for(text: str) -> tuple[str, str] | None:
    blob = clean(" ".join(glances(text) + takeaways(text) + [lede_of(text), meta_desc(text)]))
    for pattern in (MONEY, DATE):
        match = pattern.search(blob)
        if not match:
            continue
        number = re.sub(r"\s+", " ", match.group(0)).strip()
        caption = caption_beside(sentence_with(blob, match), number)
        if caption:
            return number, caption
    word = re.search(
        r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty)\b"
        r"\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,4})",
        blob,
        re.I,
    )
    if word:
        caption = fit(word.group(2), 42)
        first = caption.split()[0].lower() if caption else ""
        if caption and first not in DANGLING and not cut_off(caption):
            return WORDS[word.group(1).lower()], caption
    return None


def icon_for(slug: str, title: str) -> str:
    blob = f"{slug} {title}".lower()
    if feetish(slug, title):
        # Simple foot outline. Used only on feet posts.
        return '<svg viewBox="0 0 80 80" fill="none" stroke="#E9D5FF" stroke-width="2.4" stroke-linecap="round"><path d="M32 62c-8-2-12-10-10-18 2-8 8-10 12-6 2 2 3 6 6 6s4-4 6-6c4-4 10-2 12 6 2 8-2 16-10 18"/><circle cx="28" cy="28" r="4"/><circle cx="38" cy="22" r="3.5"/><circle cx="48" cy="22" r="3.5"/><circle cx="56" cy="28" r="3"/></svg>'
    if any(word in blob for word in ("cam", "omegle", "chat")):
        return '<svg viewBox="0 0 80 80" fill="none" stroke="#E9D5FF" stroke-width="2.4"><rect x="14" y="22" width="38" height="28" rx="6"/><path d="M52 34l14-8v28l-14-8z"/></svg>'
    if any(word in blob for word in ("privacy", "vpn", "safe", "scam", "malware")):
        return '<svg viewBox="0 0 80 80" fill="none" stroke="#E9D5FF" stroke-width="2.4"><path d="M40 12l20 8v16c0 14-8 24-20 30C28 60 20 50 20 36V20z"/><path d="M32 40l6 6 12-14"/></svg>'
    if "ai" in blob or "companion" in blob:
        return '<svg viewBox="0 0 80 80" fill="none" stroke="#E9D5FF" stroke-width="2.4"><rect x="18" y="24" width="44" height="32" rx="8"/><circle cx="32" cy="40" r="3"/><circle cx="48" cy="40" r="3"/><path d="M32 16h16M40 16v8"/></svg>'
    return '<svg viewBox="0 0 80 80" fill="none" stroke="#E9D5FF" stroke-width="2.4"><rect x="26" y="10" width="28" height="50" rx="6"/><circle cx="40" cy="52" r="2"/></svg>'


def stat_label(number: str, caption: str) -> str:
    blob = f"{number} {caption}".lower()
    if "allowance" in blob or "hmrc" in blob or "trading income" in blob:
        return "Trading allowance"
    if "million" in blob or "gross" in blob:
        return "Reported gross"
    if re.search(r"20\d{2}", number):
        return "On the record"
    if "%" in number or "percent" in number.lower():
        return "The cut"
    if number.replace(",", "").isdigit():
        return "In this guide"
    if "$" in number or "£" in number or "€" in number:
        return "Listed price"
    return "From this guide"


def side_html(text: str, slug: str, title: str) -> str:
    fact = fact_for(text)
    if fact:
        number, caption = fact
        size = 72 if len(number) <= 6 else 52 if len(number) <= 12 else 36
        return (
            f'<aside class="card stat"><p class="label">{esc(stat_label(number, caption))}</p>'
            f'<p class="num" style="font-size:{size}px">{esc(number)}</p>'
            f'<p class="cap">{esc(caption)}</p></aside>'
        )
    heads = headings(text)
    if len(heads) >= 3:
        items = "".join(
            f"<li><b>{index:02d}</b><span>{esc(fit(head, 36))}</span></li>"
            for index, head in enumerate(heads[:4], start=1)
        )
        return f'<aside class="card list"><p class="label">In this guide</p><ol>{items}</ol></aside>'
    return f'<aside class="card icon">{icon_for(slug, title)}</aside>'


def cover_html(post: dict) -> str:
    chips = "".join(f"<span><i></i>{esc(item)}</span>" for item in post["chips"])
    length = len(post["title"])
    size = 84 if length <= 28 else 76 if length <= 42 else 68
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
@font-face{{font-family:'Bricolage Grotesque';src:url('{FONT_URI}') format('woff2');font-weight:200 800;font-style:normal;font-display:block}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1200px;height:630px;overflow:hidden;background:#0c0914}}
body,.kicker,h1,.sub,.chips span,.label,.num,.cap,.list li,.brand,.hook{{font-family:'Bricolage Grotesque',sans-serif}}
body{{color:#fff}}
.cover{{width:1200px;height:630px;display:flex;flex-direction:column;position:relative;overflow:hidden;
  background:linear-gradient(165deg,#2a1848 0%, #160d28 42%, #0c0914 100%)}}
.orb{{position:absolute;width:520px;height:520px;border-radius:50%;right:-140px;top:-180px;
  background:radial-gradient(circle, rgba(139,92,246,.62), rgba(109,40,217,.18) 42%, transparent 70%);filter:blur(2px)}}
.orb.b{{width:380px;height:380px;left:-120px;bottom:-40px;top:auto;right:auto;
  background:radial-gradient(circle, rgba(124,58,237,.35), transparent 68%)}}
.stars{{position:absolute;inset:0;pointer-events:none;
  background-image:
    radial-gradient(1.4px 1.4px at 8% 18%, rgba(244,238,255,.85), transparent),
    radial-gradient(1.2px 1.2px at 22% 62%, rgba(233,213,255,.7), transparent),
    radial-gradient(1.6px 1.6px at 40% 28%, rgba(255,255,255,.75), transparent),
    radial-gradient(1px 1px at 58% 70%, rgba(196,162,255,.8), transparent),
    radial-gradient(1.3px 1.3px at 73% 22%, rgba(255,255,255,.7), transparent),
    radial-gradient(1px 1px at 86% 48%, rgba(233,213,255,.65), transparent),
    radial-gradient(rgba(233,213,255,.45) .7px, transparent .9px);
  background-size:auto,auto,auto,auto,auto,auto,26px 26px}}
.main{{position:relative;flex:1;display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:40px;align-items:center;padding:36px 52px 12px}}
.kicker{{display:flex;align-items:center;gap:12px;color:#E9D5FF;font-size:16px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}}
.kicker:before{{content:"";width:34px;height:3px;background:#C4A2FF;border-radius:2px}}
h1{{margin-top:14px;font-size:{size}px;line-height:.98;font-weight:700;letter-spacing:-.035em}}
h1 em{{font-style:normal;color:#E9D5FF;box-shadow:inset 0 -7px 0 rgba(196,162,255,.5)}}
.sub{{margin-top:14px;color:#D5CCE8;font-size:22px;line-height:1.3;max-width:36ch;font-weight:500}}
.chips{{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px;max-width:620px}}
.chips span{{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border-radius:999px;
  background:rgba(20,12,36,.62);border:1px solid rgba(196,162,255,.4);color:#F7F2FF;font-size:16px;font-weight:650}}
.chips i{{width:8px;height:8px;border-radius:50%;background:#C4A2FF;display:block}}
.card{{border-radius:26px;background:linear-gradient(180deg, rgba(48,30,84,.82), rgba(16,10,28,.92));
  border:1px solid rgba(196,162,255,.4);box-shadow:inset 0 1px 0 rgba(255,255,255,.1), 0 18px 40px rgba(0,0,0,.28);
  padding:22px 24px 20px}}
.label{{color:#C4A2FF;font-size:13px;letter-spacing:.16em;text-transform:uppercase;font-weight:700}}
.num{{margin-top:8px;font-weight:700;letter-spacing:-.04em;line-height:.92;color:#fff}}
.cap{{margin-top:10px;color:#DDD4EE;font-size:18px;line-height:1.3;font-weight:500}}
.list ol{{list-style:none;display:flex;flex-direction:column;gap:12px;margin-top:14px}}
.list li{{display:flex;gap:12px;align-items:flex-start;color:#F4EEFF;font-size:17px;line-height:1.25;font-weight:650}}
.list b{{color:#C4A2FF;font-weight:700;font-variant-numeric:tabular-nums}}
.icon{{align-items:center;display:flex;justify-content:center;min-height:220px}}
.icon svg{{width:150px;height:150px}}
.bar{{position:relative;height:88px;display:flex;align-items:center;justify-content:space-between;gap:24px;
  padding:0 40px;background:rgba(8,6,14,.78);border-top:1px solid rgba(196,162,255,.3)}}
.brand{{display:flex;align-items:center;gap:12px;font-size:30px;font-weight:700;letter-spacing:-.03em}}
.brand b{{font-weight:700}}
.brand span{{color:#C4A2FF}}
.hook{{color:#E7DFF6;font-size:20px;font-weight:550;text-align:right;max-width:680px}}
</style></head><body><div class="cover"><div class="orb"></div><div class="orb b"></div><div class="stars"></div><div class="main"><div>
<p class="kicker">{esc(post["kicker"])}</p>
<h1>{post["title_html"]}</h1>
<p class="sub">{esc(post["subtitle"])}</p>
<div class="chips">{chips}</div>
</div>{post["side"]}</div>
<footer class="bar"><div class="brand">{LOGO}<div><b>Dark</b><span>-Ero</span></div></div>
<p class="hook">{esc(post["hook"])}</p></footer></div></body></html>"""


def build_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    title = field(text, "h1") or path.parent.name.replace("-", " ").title()
    title = re.sub(r"\s*\|\s*Dark-Ero\s*$", "", title).strip()
    lede = lede_of(text) or meta_desc(text)
    slug = path.parent.name
    subtitle = one_line(lede, 70)
    notes = takeaways(text) + glances(text)[1:]
    hook = ""
    for note in notes:
        line = one_line(note, 78)
        if len(line) >= 24 and line.lower() != subtitle.lower() and not cut_off(line):
            hook = line
            break
    if not hook:
        hook = "Prices, rules and risks checked for this guide"
    return {
        "path": path,
        "slug": slug,
        "title": title,
        "title_html": accent_title(title),
        "kicker": kicker_for(path, title),
        "subtitle": subtitle,
        "chips": chips_for(text),
        "side": side_html(text, slug, title),
        "hook": hook,
        "text": text,
    }


def jpeg_bytes(page, html_text: str) -> bytes:
    page.set_content(html_text, wait_until="load")
    loaded = page.evaluate(
        """async () => {
          await document.fonts.ready;
          await document.fonts.load("700 80px 'Bricolage Grotesque'");
          return document.fonts.check("700 80px 'Bricolage Grotesque'");
        }"""
    )
    if not loaded:
        raise SystemExit("Bricolage Grotesque did not load")
    data = b""
    for quality in (76, 68, 58, 48, 40):
        data = page.screenshot(type="jpeg", quality=quality, clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        if len(data) <= 120 * 1024:
            return data
    return data


def ensure_og(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if 'property="og:image"' in text or "property='og:image'" in text:
        return
    rel = path.parent.relative_to(ROOT).as_posix()
    url = f"https://www.dark-ero.store/{rel}/cover.jpg"
    tags = (
        f'<meta property="og:image" content="{url}">'
        f'<meta name="twitter:image" content="{url}">'
    )
    if 'name="twitter:card"' not in text:
        tags = '<meta name="twitter:card" content="summary_large_image">' + tags
    path.write_text(text.replace("</head>", tags + "</head>", 1), encoding="utf-8")


def main() -> None:
    only = None
    write = "--write" in sys.argv
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    posts = [build_post(path) for path in targets()]
    if only:
        posts = [post for post in posts if post["slug"] in only or post["path"].parent.relative_to(ROOT).as_posix() in only]
    out_dir = Path("/opt/cursor/artifacts/covers")
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        for post in posts:
            data = jpeg_bytes(page, cover_html(post))
            sample = out_dir / f"{post['slug']}.jpg"
            sample.write_bytes(data)
            if write:
                dest = post["path"].parent / "cover.jpg"
                dest.write_bytes(data)
                ensure_og(post["path"])
                image = Image.open(dest)
                if image.size != (1200, 630):
                    raise SystemExit(f"bad size {dest}")
            print(f"{post['slug']:48} {len(data):6}  {post['kicker']}")
        browser.close()
    print(f"rendered {len(posts)}")


if __name__ == "__main__":
    main()
