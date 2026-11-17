#!/usr/bin/env python3
"""Wrap each single-platform review in the shared Dark-Ero review layout.

Article text is left in place. The script only adds the hero card, verdict
sidebar and stylesheet. Scores come from the page's own ratingValue.

It also inserts one mid-article call-to-action before the h2 nearest the
middle of the article, so later review pages get the same button.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPARE = {
    "chaturbate-review": ("/comparisons/chaturbate-vs-stripchat/", "Compare cam sites"),
    "stripchat-review": ("/comparisons/chaturbate-vs-stripchat/", "Compare cam sites"),
}
STOP = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "by",
    "with", "from", "is", "are", "was", "be", "this", "that", "its", "it",
}
HERO_RE = re.compile(
    r'<section class="pg-hero"><div class="in"><h1>(.*?)</h1><p class="lede">(.*?)</p>'
    r'<div class="pills">(.*?)</div>(<figure class="cover">.*?</figure>)</div></section>',
    re.S,
)
MAIN_RE = re.compile(
    r'<main class="container wrap2" id="main">(.*?)<div class="doc">\s*'
    r'(<nav class="side-toc".*?</nav>)\s*(<article class="prose">.*?</article>)\s*</div>\s*</main>',
    re.S,
)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def score_of(text: str) -> str | None:
    match = re.search(r'"ratingValue"\s*:\s*"(\d+(?:\.\d+)?)"', text)
    return match.group(1) if match else None


def platform_name(text: str, title: str) -> str:
    match = re.search(r'"itemReviewed"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', text)
    if match:
        return html.unescape(match.group(1))
    head = re.split(r"\s+Review\b", clean(title), maxsplit=1)[0].strip()
    return head or clean(title)


def year_label(title: str) -> str:
    return "Review 2026" if re.search(r"\bReview\s+20\d{2}\b", title) else "Review"


def emphasize(lede: str) -> str:
    """Bold a few existing words. The sentence itself is unchanged."""
    count = 0

    def wrap(match: re.Match) -> str:
        nonlocal count
        word = match.group(0)
        if count >= 3 or word.lower() in STOP or len(word) < 4:
            return word
        count += 1
        return f"<strong>{word}</strong>"

    return re.sub(r"[A-Za-z][A-Za-z'-]+", wrap, lede)


def category_link(text: str) -> tuple[str, str]:
    match = re.search(
        r'class="crumbs".*?href="(?:https://www\.dark-ero\.store)?(/category/[^"]+)"[^>]*>([^<]+)',
        text,
        re.S,
    )
    if not match:
        return "/reviews/", "All reviews"
    return match.group(1), clean(match.group(2))


def updated(pills: str) -> str:
    match = re.search(r"Updated\s+([^<]+)", pills)
    return f"Updated {clean(match.group(1))}" if match else ""


def verdict(score: str | None) -> tuple[str, str]:
    if not score:
        return "Unscored", ""
    value = float(score)
    if value >= 7.5:
        return "Recommended", "rec"
    if value >= 5.5:
        return "Conditional", ""
    return "Caution", ""


def ring(score: str) -> str:
    percent = max(0, min(100, round(float(score) * 10)))
    return (
        f'<div class="rv-dial" aria-label="Score {esc(score)} out of 10">'
        '<svg class="rv-ring" viewBox="0 0 36 36" aria-hidden="true">'
        '<circle cx="18" cy="18" r="15.5" pathLength="100" fill="none" stroke="#efe6d2" stroke-width="3"/>'
        f'<circle cx="18" cy="18" r="15.5" pathLength="100" fill="none" stroke="#c4a15a" stroke-width="3" '
        f'stroke-linecap="round" stroke-dasharray="{percent} 100" transform="rotate(-90 18 18)"/>'
        "</svg>"
        f'<p class="rv-num">{esc(score)}<small>/10</small></p></div>'
    )


def logo_html(slug: str, name: str) -> str:
    path = ROOT / "assets" / "logos" / f"{slug}.webp"
    if path.is_file():
        return (
            f'<span class="rv-logo"><img src="/assets/logos/{slug}.webp" width="64" height="64" '
            f'alt="" decoding="async"></span>'
        )
    letters = "".join(word[0] for word in re.findall(r"[A-Za-z0-9]+", name)[:2]).upper() or "DE"
    return f'<span class="rv-logo"><span class="rv-mark">{esc(letters)}</span></span>'


def glance_line(block: str) -> str:
    match = re.search(r'<p class="g-row[^"]*">(.*?)</p>', block, re.S)
    return clean(match.group(1)) if match else ""


CTA_HREF = "https://auctionr.org/4/fa287f925fa1b4eacf25649067392482"
CTA_HTML = (
    '<div class="cta2 cta-actions">'
    f'<a class="btn btn-primary" href="{CTA_HREF}" '
    'target="_blank" rel="nofollow sponsored noopener">Explore Top Picks</a></div>'
)
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
BLOCKED_PARENTS = {"p", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "details"}


class _ReviewArticle(HTMLParser):
    """Locate the prose article and its top-level section headings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, int, dict[str, str]]] = []
        self.article_open: int | None = None
        self.article_close: int | None = None
        self.in_article = False
        self.h2s: list[dict] = []
        self.boundaries: list[int] = []
        self._h2: dict | None = None
        self._buf: list[str] = []

    def _index(self) -> int:
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        index = self._index()
        attr = {key: value or "" for key, value in attrs}
        if tag == "article" and self.article_open is None and "prose" in attr.get("class", "").split():
            self.in_article = True
            self.article_open = index
        if self.in_article and _is_boundary(tag, attr):
            self.boundaries.append(index)
        self.stack.append((tag, index, attr))
        if tag == "h2" and self.in_article:
            self._h2 = {
                "start": index,
                "id": attr.get("id", ""),
                "text": "",
                "parents": [(name, parent.get("class", ""), parent.get("id", "")) for name, _, parent in self.stack[:-1]],
            }
            self._buf = []
        if tag in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        index = self._index()
        if tag == "h2" and self._h2 is not None:
            self._h2["text"] = "".join(self._buf).strip()
            self.h2s.append(self._h2)
            self._h2 = None
        if tag == "article" and self.in_article and self.stack and self.stack[-1][0] == "article":
            self.article_close = index
            self.in_article = False
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        if self._h2 is not None:
            self._buf.append(data)


def _is_boundary(tag: str, attr: dict[str, str]) -> bool:
    ident = attr.get("id", "").lower()
    classes = set(attr.get("class", "").lower().split())
    if ident == "faq" or "faq" in classes or "faq-list" in classes:
        return True
    if ident.startswith("related-") or "related-cats" in classes:
        return True
    return False


def _visible_len(fragment: str) -> int:
    return len(re.sub(r"<[^>]*>", "", fragment))


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    start = 0
    while True:
        found = text.find("\n", start)
        if found < 0:
            return offsets
        offsets.append(found + 1)
        start = found + 1


def ensure_mid_cta(text: str) -> tuple[str, str]:
    """Insert one themed CTA before the h2 nearest the middle of a review article.

    The link sits between sections. It is never placed inside a paragraph,
    table, or FAQ. Pages that already contain the link are left unchanged.
    """
    if CTA_HREF in text:
        return text, "already present"
    parser = _ReviewArticle()
    parser.line_offsets = _line_offsets(text)
    parser.feed(text)
    if parser.article_open is None or parser.article_close is None:
        return text, "skipped: no prose article"
    open_end = text.find(">", parser.article_open)
    if open_end < 0:
        return text, "skipped: article tag did not close"
    open_end += 1
    content_end = parser.article_close
    for boundary in parser.boundaries:
        if open_end <= boundary < content_end:
            content_end = boundary
    eligible: list[tuple[int, dict]] = []
    for heading in parser.h2s:
        if heading["start"] < open_end or heading["start"] >= content_end:
            continue
        if heading["id"].lower() == "faq" or heading["text"].strip().lower() in {"faq"} or heading["text"].strip().lower().endswith(" faq"):
            continue
        parents = [name for name, _, _ in heading["parents"]]
        if parents and parents[-1] != "article":
            continue
        if any(name in BLOCKED_PARENTS or name == "section" for name in parents):
            continue
        eligible.append((heading["start"], heading))
    if len(eligible) < 2:
        return text, "skipped: fewer than two section headings before the FAQ"
    total = _visible_len(text[open_end:content_end])
    if total <= 0:
        return text, "skipped: article has no text before the FAQ"
    midpoint = total / 2
    ranked = sorted(eligible, key=lambda item: abs(_visible_len(text[open_end:item[0]]) - midpoint))
    chosen = ranked[0]
    if chosen[0] == eligible[0][0]:
        chosen = next(item for item in ranked if item[0] != eligible[0][0])
    heading = chosen[1]
    offset = _visible_len(text[open_end:heading["start"]])
    percent = round(100 * offset / total, 1)
    snippet = CTA_HTML + "\n"
    updated = text[: heading["start"]] + snippet + text[heading["start"] :]
    return updated, f"placed before #{heading['id'] or heading['text']} at {percent}%"


def transform(text: str, slug: str) -> str:
    text, _info = ensure_mid_cta(text)
    if 'class="rv-page"' in text:
        return text
    hero = HERO_RE.search(text)
    main = MAIN_RE.search(text)
    if not hero or not main:
        raise SystemExit(f"layout markers missing in {slug}")
    title = clean(hero.group(1))
    lede = hero.group(2)
    name = platform_name(text, title)
    score = score_of(text)
    label, tone = verdict(score)
    href, cat_name = category_link(text)
    button = f"Browse {cat_name}"
    if slug in COMPARE:
        href, button = COMPARE[slug]
    price = glance_line(main.group(1))
    price_label = "Pricing" if re.search(r"[$£€%]|fee|price", price, re.I) else "Snapshot"
    rest = title
    prefix = f"{name} {year_label(title)}"
    if title.lower().startswith(prefix.lower()):
        rest = title[len(prefix):]
    elif title.lower().startswith(name.lower()):
        rest = title[len(name):]
    hidden = f'<span class="rv-rest">{esc(rest)}</span>' if rest else ""
    score_tag = f'<p class="rv-scoretag">Score {esc(score)}/10</p>' if score else ""
    ring_html = ring(score) if score else ""
    date = updated(hero.group(3))
    date_html = f'<p class="rv-updated">{esc(date)}</p>' if date else ""
    card = (
        '<div class="rv-page"><section class="rv-hero"><div class="rv-hero-card"><div>'
        f'<h1 class="rv-h1">{esc(name)} <span class="rv-year">{esc(year_label(title))}</span>{hidden}</h1>'
        f'<p class="lede">{emphasize(lede)}</p>'
        '<p class="rv-pill">Independent review · 18+</p>'
        f"{date_html}</div><div class=\"rv-brand\">"
        f"{logo_html(slug, name)}<p class=\"rv-plat\">{esc(name)}</p>{score_tag}</div></div></section>"
    )
    # Keep the cover figure, just add rv-cover alongside cover.
    cover = hero.group(4).replace('class="cover"', 'class="cover rv-cover"', 1)
    verdict_html = (
        '<aside class="rv-verdict" aria-label="Our verdict"><p class="rv-k">Our verdict</p>'
        '<div class="rv-scoreline">'
        f"{ring_html}<span class=\"rv-pillv {tone}\">{esc(label)}</span></div>"
        f'<p class="rv-price"><strong>{esc(price_label)}.</strong> {esc(price)}</p>'
        f'<a class="rv-go" href="{esc(href)}">{esc(button)}</a></aside>'
    )
    toc = main.group(2).replace("<nav ", '<nav class="rv-toc" ', 1)
    # The original nav already has class="side-toc". Putting class on the replacement
    # above would drop side-toc. Keep both classes.
    toc = main.group(2).replace(
        'class="side-toc"',
        'class="side-toc rv-toc"',
        1,
    )
    layout = (
        card
        + cover
        + '<div class="rv-layout"><div class="rv-main">'
        + main.group(1)
        + main.group(3)
        + '</div><div class="rv-side">'
        + verdict_html
        + toc
        + "</div></div></div>"
    )
    text = text[: hero.start()] + layout + text[main.end():]
    if 'href="/assets/review-layout.css"' not in text:
        text = text.replace(
            "</head>",
            '<link rel="stylesheet" href="/assets/review-layout.css"></head>',
            1,
        )
    if 'src="/assets/review-layout.js"' not in text:
        text = text.replace(
            "</body>",
            '<script src="/assets/review-layout.js" defer></script></body>',
            1,
        )
    return text


def main() -> None:
    done = 0
    placed = 0
    skipped: list[str] = []
    for path in sorted(ROOT.glob("*-review/index.html")):
        slug = path.parent.name
        original = path.read_text(encoding="utf-8")
        updated, info = ensure_mid_cta(original)
        if 'class="rv-page"' not in updated:
            updated = transform(updated, slug)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            done += 1
        if info.startswith("placed") or info == "already present":
            placed += 1
        else:
            skipped.append(f"{slug}: {info}")
        print(f"{slug}: {info}")
    print(f"updated {done}; with button {placed}; skipped {len(skipped)}")
    for line in skipped:
        print(line)


if __name__ == "__main__":
    main()
