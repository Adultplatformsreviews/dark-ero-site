#!/usr/bin/env python3
"""Split long prose paragraphs so each one has at most two sentences.

Only plain-prose <p> elements in the main article or intro are changed.
Head, JSON-LD, metas, nav, header, footer, buttons, tables, lists, schema
FAQ text, directory-card blurbs, and paragraphs that already have one or
two sentences are left untouched.

Wording, inline tags, attributes, URLs, and the sitemap are not rewritten.
A sentence boundary inside an inline tag (or an abbreviation or number such
as "e.g.", "vs.", "$6.99", "U.S.", "Dr.") is not a split point. Each new
paragraph keeps the original <p> tag, including its class and attributes.

Client-nav copies in assets/pages/<path>.json get the same breaks, because
those bodies are the pages the directory app swaps in.

Usage:
  python3 scripts/split-paragraphs.py            # dry-run
  python3 scripts/split-paragraphs.py --write    # update HTML and JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Utility and legal pages are not article or intro copy.
EXCLUDED_REL = {
    "about/index.html",
    "contact/index.html",
    "privacy/index.html",
    "terms/index.html",
    "dmca/index.html",
    "legal-2257/index.html",
    "submit/index.html",
}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
SKIP_TAGS = {
    "head", "header", "footer", "nav", "table", "thead", "tbody", "tfoot",
    "tr", "td", "th", "ul", "ol", "li", "button", "form", "aside", "figure",
    "figcaption", "svg", "noscript", "template", "script", "style", "a",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dl",
}
# Directory grids, chrome, summaries, and calls to action.
SKIP_CLASSES = {
    "site-card", "card-grid", "post-card", "post-list", "vip-grid", "vip-rich",
    "vip-card", "vip-body", "vip-box", "vip-feature", "vip-guides", "cat-guides",
    "glance", "rv-verdict", "rv-side", "toc", "m-toc", "side-toc", "quick",
    "tpd-col", "tpd-col-h", "tpd-list", "tpd-side", "tpd-index", "tpd-cols",
    "panel", "panel-grid", "filter-bar", "crumbs", "crumb-bar", "cards", "card",
    "gate", "gate-card", "gate-actions", "age-gate", "modal",
    "cta", "cta2", "cta-band", "cta-actions",
    "de-foot", "site-foot", "head-strip", "searchbar", "nav-main", "head-links",
    "related-cats", "takeaways",
}
SKIP_P_CLASSES = {
    "toc-h", "badge", "card-t", "score", "g-row", "back-cat", "hero-eye",
    "rv-price", "rv-pill", "rv-updated", "rv-plat", "rv-scoretag",
    "tpd-side-h", "kicker", "age-mini", "vip-kicker", "vip-cta", "vip-date",
    "info-kicker", "info-h", "info-sub",
}
# Never a sentence boundary, even when the next word is capitalized.
TITLE_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "gen", "sen",
    "rep", "gov",
}
# Never a boundary. "e.g. The example" and "Chaturbate vs. Stripchat" stay whole.
ALWAYS_ABBREV = {"eg", "ie", "vs"}
# Not a boundary when the next word is lowercase or a number ("Inc. of", "No. 5").
# A capital after these still starts a sentence ("Bumble Inc. The same company").
SOFT_ABBREV = {
    "etc", "inc", "ltd", "co", "corp", "fig", "vol", "ave", "blvd", "rd",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "al", "no", "phd", "ca", "approx", "est",
}
INLINE_TAGS = {
    "em", "strong", "span", "b", "i", "small", "sup", "sub", "mark", "u", "s",
    "cite", "q", "abbr", "code", "time", "dfn", "kbd", "var", "bdi", "bdo",
    "data", "a",
}
CLOSERS = set("\"')]}”’»›")
OPENERS = set("\"'“‘(«‹")
ENTITY_RE = re.compile(r"&(#x[0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);")
HREF_RE = re.compile(r"""(?i)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
TAG_LEAD_RE = re.compile(r"^/?\s*([A-Za-z][A-Za-z0-9:-]*)")
JSON_LD_RE = re.compile(
    r"(?is)<script\s+type=[\"']application/ld\+json[\"']\s*>.*?</script>"
)
RATING_META_RE = re.compile(r"(?is)<meta\b[^>]*\bname\s*=\s*[\"']rating[\"']")


def class_list(tag: str) -> list[str]:
    match = re.search(r"""(?i)\bclass\s*=\s*(["'])(.*?)\1""", tag)
    if match:
        return match.group(2).split()
    match = re.search(r"""(?i)\bclass\s*=\s*([^\s>]+)""", tag)
    return match.group(1).split() if match else []


def tag_name(tag: str) -> str:
    inner = tag[1:-1].strip()
    if inner.endswith("/"):
        inner = inner[:-1].strip()
    match = TAG_LEAD_RE.match(inner)
    return match.group(1).lower() if match else ""


def is_end_tag(tag: str) -> bool:
    return tag.startswith("</")


def is_self_closing(tag: str, name: str) -> bool:
    return name in VOID_TAGS or tag.rstrip().endswith("/>")


def iter_tags(html: str, start: int = 0, end: int | None = None):
    """Yield (kind, tag_html, abs_start, abs_end), skipping raw script/style bodies."""
    if end is None:
        end = len(html)
    i = start
    while i < end:
        lt = html.find("<", i, end)
        if lt < 0:
            break
        if html.startswith("<!--", lt):
            close = html.find("-->", lt + 4, end)
            if close < 0:
                break
            yield "comment", html[lt:close + 3], lt, close + 3
            i = close + 3
            continue
        quote = None
        j = lt + 1
        while j < end:
            char = html[j]
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                j += 1
                break
            j += 1
        else:
            break
        tok = html[lt:j]
        name = tag_name(tok)
        yield "tag", tok, lt, j
        if not is_end_tag(tok) and name in {"script", "style"}:
            closer = re.search(rf"(?i)</{re.escape(name)}\s*>", html[j:end])
            if not closer:
                break
            i = j + closer.end()
            continue
        i = j


def line_indent(html: str, index: int) -> str:
    line_start = html.rfind("\n", 0, index) + 1
    return re.match(r"[ \t]*", html[line_start:index]).group(0)


def decode_text(text: str, html_offset: int):
    """Yield (visible_char, html_index) for a text node."""
    i = 0
    while i < len(text):
        if text[i] == "&":
            match = ENTITY_RE.match(text, i)
            if match:
                decoded = unescape(match.group(0)) or match.group(0)
                for n, char in enumerate(decoded):
                    yield char, html_offset + i if n == 0 else html_offset + i
                i = match.end()
                continue
        yield text[i], html_offset + i
        i += 1


def abbrev_suppresses(visible: str, period_index: int, next_index: int) -> bool:
    """True when the period belongs to an abbreviation or initial, not a sentence."""
    j = period_index - 1
    while j >= 0 and (visible[j].isalpha() or visible[j] == "."):
        j -= 1
    raw = visible[j + 1:period_index]
    if not raw:
        return False
    prev = visible[j] if j >= 0 else ""
    # "16K." and "24K." end the sentence. "J. Smith" does not.
    if re.fullmatch(r"[A-Za-z]", raw):
        return not prev.isdigit()
    # "21st." is an ordinal, not "St." the abbreviation.
    if prev.isdigit():
        return False
    # A dotted token is an abbreviation only when every piece is short
    # ("U.S.", "e.g.", "Ph.D."). "www.dark-ero.store." is a domain, and the
    # period after it can end the sentence.
    if "." in raw:
        segments = [re.sub(r"[^A-Za-z]", "", part) for part in raw.split(".")]
        segments = [part for part in segments if part]
        if not segments or any(len(part) > 2 for part in segments):
            return False
        letters = "".join(segments).lower()
        if letters in ALWAYS_ABBREV:
            return True
        nxt = visible[next_index]
        return nxt.islower() or nxt.isdigit()
    letters = re.sub(r"[^A-Za-z]", "", raw).lower()
    if not letters:
        return False
    if letters in ALWAYS_ABBREV or letters in TITLE_ABBREV:
        return True
    nxt = visible[next_index]
    if letters in SOFT_ABBREV and (nxt.islower() or nxt.isdigit()):
        return True
    return False


def find_paragraph_end(html: str, content_start: int) -> tuple[int, int] | None:
    """Return the span of the matching </p>, or None if the paragraph is not clean."""
    for kind, tok, start, end in iter_tags(html, content_start):
        if kind != "tag":
            continue
        name = tag_name(tok)
        if name != "p":
            continue
        if is_end_tag(tok):
            return start, end
        return None
    return None


def is_plain_prose(inner: str) -> bool:
    """False when the paragraph contains a block, media, or interactive element."""
    for kind, tok, _start, _end in iter_tags(inner):
        if kind != "tag" or tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if not name or is_end_tag(tok) or is_self_closing(tok, name):
            continue
        if name not in INLINE_TAGS:
            return False
    return True


def find_sentences(inner: str) -> list[dict] | None:
    """Sentence spans inside one paragraph. None when there is nothing to split."""
    chars: list[tuple[str, int, int]] = []
    depth = 0
    last = 0
    pieces: list[tuple[str, str, int]] = []
    for kind, tok, start, end in iter_tags(inner):
        if start > last:
            pieces.append(("text", inner[last:start], last))
        pieces.append(("tag", tok, start))
        last = end
    if last < len(inner):
        pieces.append(("text", inner[last:], last))

    for kind, tok, start in pieces:
        if kind == "text":
            for char, html_i in decode_text(tok, start):
                chars.append((char, html_i, depth))
            continue
        if tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if is_end_tag(tok):
            if name in INLINE_TAGS and depth:
                depth -= 1
            continue
        if is_self_closing(tok, name):
            if name == "br":
                chars.append(("\n", start + len(tok), depth))
            continue
        if name in INLINE_TAGS:
            depth += 1

    if not chars:
        return None
    visible = "".join(item[0] for item in chars)
    boundaries: list[int] = []
    i = 0
    n = len(visible)
    while i < n:
        char = visible[i]
        if char in ".!?":
            if char == "." and i + 1 < n and visible[i + 1] == ".":
                i += 1
                continue
            # "$6.99" and "7.5" — the dot is between digits.
            if char == "." and i > 0 and visible[i - 1].isdigit() and i + 1 < n and visible[i + 1].isdigit():
                i += 1
                continue
            j = i + 1
            while j < n and visible[j] in CLOSERS:
                j += 1
            # "AdmireMe.VIP" and "www.dark-ero.store" have no space after the dot.
            if j >= n or not visible[j].isspace():
                i += 1
                continue
            k = j
            while k < n and visible[k].isspace():
                k += 1
            if k >= n:
                break
            nxt = visible[k]
            if not (nxt.isupper() or nxt.isdigit() or nxt in OPENERS):
                i += 1
                continue
            if char == "." and abbrev_suppresses(visible, i, k):
                i += 1
                continue
            boundaries.append(k)
            i = k
            continue
        i += 1

    starts = [0]
    for boundary in boundaries:
        if boundary > starts[-1]:
            starts.append(boundary)
    sentences = []
    for idx, vis_start in enumerate(starts):
        vis_end = starts[idx + 1] if idx + 1 < len(starts) else n
        plain = visible[vis_start:vis_end].strip()
        if not plain:
            continue
        html_start = 0 if not sentences else chars[vis_start][1]
        if idx + 1 < len(starts):
            html_end = chars[starts[idx + 1]][1]
        else:
            html_end = len(inner)
        # A boundary is usable only when the next sentence does not begin
        # inside <a>, <em>, <strong>, or any other inline tag.
        splittable = bool(sentences) and chars[vis_start][2] == 0
        sentences.append({
            "plain": plain,
            "html_start": html_start,
            "html_end": html_end,
            "splittable_before": splittable,
        })
    if len(sentences) < 3:
        return None
    return sentences


def pack_sentences(sentences: list[dict]) -> list[list[dict]] | None:
    """Pair sentences. None when a pair would have to cut an inline tag."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for sentence in sentences:
        if not current:
            current = [sentence]
            continue
        if len(current) >= 2:
            if not sentence["splittable_before"]:
                return None
            groups.append(current)
            current = [sentence]
            continue
        current.append(sentence)
    if current:
        groups.append(current)
    if len(groups) < 2 or any(len(group) > 2 for group in groups):
        return None
    return groups


def plain_text(html: str) -> str:
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def anchors_in(html: str) -> list[str]:
    found = []
    stack: list[int] = []
    for kind, tok, start, end in iter_tags(html):
        if kind != "tag":
            continue
        name = tag_name(tok)
        if name != "a":
            continue
        if is_end_tag(tok):
            if stack:
                open_at = stack.pop()
                found.append(html[open_at:end])
        elif not is_self_closing(tok, name):
            stack.append(start)
    return found


def split_paragraph(full: str, indent: str) -> str | None:
    """Replacement HTML for one <p>...</p>, or None to leave it unchanged."""
    open_match = re.match(r"(?is)<p\b[^>]*>", full)
    close_match = re.search(r"(?is)</p\s*>$", full)
    if not open_match or not close_match:
        return None
    open_tag = open_match.group(0)
    close_tag = close_match.group(0)
    inner = full[open_match.end():close_match.start()]
    if not is_plain_prose(inner):
        return None
    sentences = find_sentences(inner)
    if not sentences:
        return None
    groups = pack_sentences(sentences)
    if not groups:
        return None
    pieces = []
    for index, group in enumerate(groups):
        start = group[0]["html_start"]
        end = group[-1]["html_end"]
        chunk = inner[start:end]
        if index != len(groups) - 1:
            chunk = chunk.rstrip(" \t\r\n")
        if index:
            chunk = chunk.lstrip(" \t\r\n")
        if not chunk.strip():
            return None
        if find_sentences(chunk):
            return None
        pieces.append(chunk)
    if plain_text(" ".join(pieces)) != plain_text(inner):
        return None
    if anchors_in("".join(pieces)) != anchors_in(inner):
        return None
    sep = "\n" + indent
    return sep.join(f"{open_tag}{piece}{close_tag}" for piece in pieces)


def ancestor_blocked(stack: list[tuple[str, set[str]]]) -> bool:
    for name, classes in stack:
        if name in SKIP_TAGS:
            return True
        if SKIP_CLASSES.intersection(classes):
            return True
    return False


def in_content_region(stack: list[tuple[str, set[str]]], p_classes: set[str]) -> bool:
    """Article body, a lede, or the homepage / hub intro."""
    if "lede" in p_classes:
        return True
    for name, classes in stack:
        if name == "article":
            return True
        if classes.intersection({"prose", "home-intro", "hub-intro"}):
            return True
    return False


def should_split(stack: list[tuple[str, set[str]]], p_tag: str) -> bool:
    p_classes = set(class_list(p_tag))
    if SKIP_P_CLASSES.intersection(p_classes):
        return False
    if ancestor_blocked(stack):
        return False
    return in_content_region(stack, p_classes)


def transform_html(html: str) -> tuple[str, int, int]:
    """Return (html, paragraphs_split, paragraphs_left_unsplit)."""
    out: list[str] = []
    cursor = 0
    stack: list[tuple[str, set[str]]] = []
    split_count = 0
    unsplit = 0
    for kind, tok, start, end in iter_tags(html):
        if kind != "tag":
            continue
        name = tag_name(tok)
        if is_end_tag(tok):
            for n in range(len(stack) - 1, -1, -1):
                if stack[n][0] == name:
                    del stack[n]
                    break
            continue
        if name in {"script", "style"}:
            continue
        if name == "p" and not is_self_closing(tok, name) and should_split(stack, tok):
            close = find_paragraph_end(html, end)
            if close:
                close_start, close_end = close
                full = html[start:close_end]
                inner = html[end:close_start]
                sentences = find_sentences(inner) if is_plain_prose(inner) else None
                replacement = split_paragraph(full, line_indent(html, start))
                if replacement and replacement != full:
                    out.append(html[cursor:start])
                    out.append(replacement)
                    cursor = close_end
                    split_count += 1
                elif sentences:
                    unsplit += 1
        if not is_self_closing(tok, name):
            stack.append((name, set(class_list(tok))))
    out.append(html[cursor:])
    return "".join(out), split_count, unsplit


def normalized_visible(html: str) -> str:
    no_script = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", html)
    no_style = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", no_script)
    no_tags = re.sub(r"(?is)<[^>]+>", " ", no_style)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def hrefs(html: str) -> list[str]:
    return [a or b or c or "" for a, b, c in HREF_RE.findall(html)]


def tag_balance_ok(html: str) -> bool:
    stack: list[str] = []
    for kind, tok, _start, _end in iter_tags(html):
        if kind != "tag" or tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if not name:
            continue
        if is_end_tag(tok):
            if name in VOID_TAGS:
                continue
            if name not in stack:
                return False
            while stack and stack[-1] != name:
                stack.pop()
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        elif not is_self_closing(tok, name):
            stack.append(name)
    return not stack


def slice_between(html: str, start_token: str, end_token: str) -> str | None:
    start = html.find(start_token)
    end = html.rfind(end_token)
    if start < 0 or end < 0 or end < start:
        return None
    return html[start:end + len(end_token)]


def validate(before: str, after: str) -> list[str]:
    problems = []
    if normalized_visible(before) != normalized_visible(after):
        problems.append("visible wording changed")
    if hrefs(before) != hrefs(after):
        problems.append("href list changed")
    if anchors_in(before) != anchors_in(after):
        problems.append("anchor elements changed")
    if JSON_LD_RE.findall(before) != JSON_LD_RE.findall(after):
        problems.append("JSON-LD changed")
    head_before = slice_between(before, "<head", "</head>")
    head_after = slice_between(after, "<head", "</head>")
    if head_before != head_after:
        problems.append("head changed")
    if RATING_META_RE.search(after) and not RATING_META_RE.search(before):
        problems.append("rating meta added")
    header_before = slice_between(before, "<header", "</header>")
    header_after = slice_between(after, "<header", "</header>")
    if header_before != header_after:
        problems.append("header changed")
    footer_before = slice_between(before, "<footer", "</footer>")
    footer_after = slice_between(after, "<footer", "</footer>")
    if footer_before != footer_after:
        problems.append("footer changed")
    if tag_balance_ok(before) and not tag_balance_ok(after):
        problems.append("tag balance broken")
    return problems


def is_content_page(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if path.name != "index.html":
        return False
    if rel in EXCLUDED_REL:
        return False
    if any(part in {"assets", "node_modules", ".git"} for part in path.parts):
        return False
    return True


def content_pages() -> list[Path]:
    return sorted(path for path in ROOT.rglob("index.html") if is_content_page(path))


def json_page_rel(path: Path) -> str | None:
    """Map assets/pages/category/fetish.json to category/fetish/index.html."""
    try:
        rel = path.relative_to(ROOT / "assets" / "pages")
    except ValueError:
        return None
    if rel.suffix != ".json":
        return None
    stem = rel.with_suffix("").as_posix()
    direct = ROOT / f"{stem}.html"
    nested = ROOT / stem / "index.html"
    if direct.is_file():
        return direct.relative_to(ROOT).as_posix()
    if nested.is_file():
        return nested.relative_to(ROOT).as_posix()
    return None


def replace_json_string(raw: str, old: str, new: str) -> str | None:
    """Replace one JSON string value without reformatting the rest of the file."""
    candidates = [
        (json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)),
        (json.dumps(old, ensure_ascii=True), json.dumps(new, ensure_ascii=True)),
    ]
    for old_enc, new_enc in candidates:
        if raw.count(old_enc) == 1:
            return raw.replace(old_enc, new_enc, 1)
    return None


def paragraph_plains(html: str) -> list[str]:
    plains = []
    for match in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", html):
        plains.append(plain_text(match.group(1)))
    return plains


def wrapped(html: str) -> str:
    return f"<main><article class=\"prose\">{html}</article></main>"


def self_test() -> None:
    cases: list[tuple[str, list[str] | None]] = [
        (
            "<p>Alpha sentence here. Beta sentence here. Gamma sentence here.</p>",
            ["Alpha sentence here. Beta sentence here.", "Gamma sentence here."],
        ),
        (
            "<p>One here. Two here. Three here. Four here.</p>",
            ["One here. Two here.", "Three here. Four here."],
        ),
        (
            "<p>Only two sentences live here. The second one stays with the first.</p>",
            None,
        ),
        (
            "<p>No. Tips and spy sessions are non-refundable once the tokens leave your balance.</p>",
            None,
        ),
        (
            "<p>No. Get A Taste keeps the same context and the same reply cap as free. It removes ads and the queue.</p>",
            [
                "No. Get A Taste keeps the same context and the same reply cap as free.",
                "It removes ads and the queue.",
            ],
        ),
        (
            "<p>Run by FLRT Inc. of Carson City, Nevada. Buyers pay a fee. Sellers keep the rest.</p>",
            [
                "Run by FLRT Inc. of Carson City, Nevada. Buyers pay a fee.",
                "Sellers keep the rest.",
            ],
        ),
        (
            "<p>Bumble Inc. The same company also runs Badoo. This page judges the dating app.</p>",
            [
                "Bumble Inc. The same company also runs Badoo.",
                "This page judges the dating app.",
            ],
        ),
        (
            "<p>It costs $6.99 today. Then it renews at $14.99. After that you can cancel.</p>",
            [
                "It costs $6.99 today. Then it renews at $14.99.",
                "After that you can cancel.",
            ],
        ),
        (
            "<p>See the note, e.g. the fee table, before you pay. A second point follows. A third point ends it.</p>",
            [
                "See the note, e.g. the fee table, before you pay. A second point follows.",
                "A third point ends it.",
            ],
        ),
        (
            "<p>Chaturbate vs. Stripchat is the whole question. Free rooms differ. Private shows differ too.</p>",
            [
                "Chaturbate vs. Stripchat is the whole question. Free rooms differ.",
                "Private shows differ too.",
            ],
        ),
        (
            "<p>Members in the U.S. pass a photo check. Members in the U.K. do not. Everyone else reads the local rule.</p>",
            [
                "Members in the U.S. pass a photo check. Members in the U.K. do not.",
                "Everyone else reads the local rule.",
            ],
        ),
        (
            "<p>Dr. Hale wrote the policy. The clinic posted it the next day. Patients can still ask for a copy.</p>",
            [
                "Dr. Hale wrote the policy. The clinic posted it the next day.",
                "Patients can still ask for a copy.",
            ],
        ),
        (
            "<p>You are on www.dark-ero.store. The name is also written Dark Ero. Browsing costs nothing.</p>",
            [
                "You are on www.dark-ero.store. The name is also written Dark Ero.",
                "Browsing costs nothing.",
            ],
        ),
        (
            '<p class="lede">Ranked by fees. There is no single best site. Adults 18+ only.</p>',
            [
                "Ranked by fees. There is no single best site.",
                "Adults 18+ only.",
            ],
        ),
        (
            "<p><em>Disclosure: Dark-Ero is independent. We have no deal with the site. Adults 18+ only.</em></p>",
            None,
        ),
    ]
    for src, expected in cases:
        doc = wrapped(src)
        out, nsplit, _unsplit = transform_html(doc)
        problems = validate(doc, out)
        if problems:
            raise SystemExit(f"self-test validate failed for {src[:70]}: {problems}")
        if expected is None:
            if nsplit:
                raise SystemExit(f"self-test unexpectedly split:\n{src}\n->\n{out}")
            continue
        plains = [plain for plain in paragraph_plains(out) if plain]
        if plains != expected:
            raise SystemExit(f"self-test mismatch\n got {plains}\n want {expected}")

    linked = (
        '<p>Read the <a href="https://example.com/review">full review. It keeps going</a> '
        "after the link. Second sentence stands alone. Third sentence ends it.</p>"
    )
    doc = wrapped(linked)
    out, nsplit, _unsplit = transform_html(doc)
    if anchors_in(out) != anchors_in(doc):
        raise SystemExit("self-test split an anchor")
    if nsplit != 1:
        raise SystemExit(f"self-test did not split around the link:\n{out}")
    first = paragraph_plains(out)[0]
    if "full review. It keeps going" not in first:
        raise SystemExit(f"self-test cut inside the link:\n{out}")

    skipped = [
        '<footer><p>One listing. Two listings. Three listings.</p></footer>',
        '<div class="site-card"><p>Card one. Card two. Card three.</p></div>',
        '<ul><li><p>Item one. Item two. Item three.</p></li></ul>',
        '<aside class="glance"><p class="g-row">Score 7.5. One pick. The other pick.</p></aside>',
        '<p class="rv-price"><strong>Snapshot.</strong> First fact. Second fact.</p>',
    ]
    for src in skipped:
        doc = f"<main><article>{src}</article></main>"
        out, nsplit, _unsplit = transform_html(doc)
        if nsplit or out != doc:
            raise SystemExit(f"self-test touched a skipped region:\n{src}\n->\n{out}")

    head = (
        '<head><meta name="description" content="One. Two. Three.">'
        '<script type="application/ld+json">{"text":"One. Two. Three."}</script></head>'
        "<main><article><p>Body one. Body two. Body three.</p></article></main>"
    )
    out, _nsplit, _unsplit = transform_html(head)
    if slice_between(head, "<head", "</head>") != slice_between(out, "<head", "</head>"):
        raise SystemExit("self-test edited the head")
    if RATING_META_RE.search(out):
        raise SystemExit("self-test added a rating meta")

    home = (
        '<div class="home-intro"><p>You are on the official site. The name is Dark Ero. '
        "Browsing costs nothing. Updated 16 November 2026.</p></div>"
    )
    out, nsplit, _unsplit = transform_html(home)
    if nsplit != 1 or len(paragraph_plains(out)) != 2:
        raise SystemExit(f"self-test missed the homepage intro:\n{out}")

    sample = wrapped("<p>One here. Two here. Three here. Four here.</p>")
    once, _n, _u = transform_html(sample)
    twice, n2, _u2 = transform_html(once)
    if twice != once or n2:
        raise SystemExit("self-test is not idempotent")
    print("self-test ok")


def process(write: bool) -> dict:
    stats = {
        "pages_scanned": 0,
        "files_changed": 0,
        "paragraphs_split": 0,
        "paragraphs_left_unsplit": 0,
        "json_changed": 0,
        "json_skipped": [],
        "skipped_invalid": [],
        "changed_files": [],
    }
    pages = content_pages()
    stats["pages_scanned"] = len(pages)
    for path in pages:
        original = path.read_text(encoding="utf-8")
        updated, nsplit, unsplit = transform_html(original)
        problems = validate(original, updated)
        if problems:
            stats["skipped_invalid"].append(
                f"{path.relative_to(ROOT)}: {', '.join(problems)}"
            )
            continue
        again, n2, _u2 = transform_html(updated)
        if again != updated or n2:
            stats["skipped_invalid"].append(
                f"{path.relative_to(ROOT)}: not idempotent"
            )
            continue
        stats["paragraphs_left_unsplit"] += unsplit
        if not nsplit or updated == original:
            continue
        stats["files_changed"] += 1
        stats["paragraphs_split"] += nsplit
        stats["changed_files"].append(path.relative_to(ROOT).as_posix())
        if write:
            path.write_text(updated, encoding="utf-8")

    for path in sorted((ROOT / "assets" / "pages").rglob("*.json")):
        rel = json_page_rel(path)
        if rel is None or rel in EXCLUDED_REL:
            continue
        page = ROOT / rel
        if not is_content_page(page):
            continue
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            stats["json_skipped"].append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, str):
            continue
        updated, nsplit, unsplit = transform_html(body)
        if not nsplit or updated == body:
            continue
        problems = validate(body, updated)
        if problems:
            stats["json_skipped"].append(
                f"{path.relative_to(ROOT)}: {', '.join(problems)}"
            )
            continue
        replaced = replace_json_string(raw, body, updated)
        if replaced is None:
            stats["json_skipped"].append(
                f"{path.relative_to(ROOT)}: body encoding did not match"
            )
            continue
        # The HTML pass already counted these paragraphs when the copy matches.
        stats["json_changed"] += 1
        stats["paragraphs_left_unsplit"] += unsplit
        if write:
            path.write_text(replaced, encoding="utf-8")
    return stats


def spot_check(paths: list[str]) -> None:
    print("\nspot-check")
    for rel in paths:
        path = ROOT / rel
        if not path.is_file():
            print(f"- {rel}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        long_ones = []
        stack: list[tuple[str, set[str]]] = []
        for kind, tok, start, end in iter_tags(text):
            if kind != "tag":
                continue
            name = tag_name(tok)
            if is_end_tag(tok):
                for n in range(len(stack) - 1, -1, -1):
                    if stack[n][0] == name:
                        del stack[n]
                        break
                continue
            if name in {"script", "style"}:
                continue
            if name == "p" and not is_self_closing(tok, name) and should_split(stack, tok):
                close = find_paragraph_end(text, end)
                if close:
                    inner = text[end:close[0]]
                    sentences = find_sentences(inner) if is_plain_prose(inner) else None
                    if sentences and len(sentences) > 2:
                        long_ones.append(plain_text(inner)[:140])
            if not is_self_closing(tok, name):
                stack.append((name, set(class_list(tok))))
        print(f"- {rel}: prose paragraphs still over 2 sentences: {len(long_ones)}")
        for sample in long_ones[:3]:
            print(f"    {sample}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write HTML and JSON files")
    args = parser.parse_args()
    self_test()
    stats = process(write=args.write)
    printable = {key: value for key, value in stats.items() if key != "changed_files"}
    printable["changed_files"] = stats["changed_files"]
    print(json.dumps(printable, indent=2))
    spot_check([
        "index.html",
        "feetfinder-review/index.html",
        "category/fetish/index.html",
        "comparisons/chaturbate-vs-stripchat/index.html",
    ])
    if stats["skipped_invalid"] or stats["json_skipped"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
