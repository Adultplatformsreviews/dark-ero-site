#!/usr/bin/env python3
"""Rebreak long article-body paragraphs into coherent ~2-sentence paragraphs.

Only paragraph boundaries change. Wording, links, anchors, headings, lists,
tables, FAQ structure, metas, and JSON-LD are left untouched. Client-nav JSON
copies (assets/pages/<path>.json) get the same paragraph breaks.

Usage:
  python3 scripts/rebreak-paragraphs.py            # dry-run
  python3 scripts/rebreak-paragraphs.py --write    # update HTML and JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Hub, listing, legal, and utility pages are not article bodies.
EXCLUDED_REL = {
    "index.html",
    "reviews/index.html",
    "blog/index.html",
    "comparisons/index.html",
    "best-lists/index.html",
    "alternatives/index.html",
    "categories/index.html",
    "about/index.html",
    "contact/index.html",
    "privacy/index.html",
    "terms/index.html",
    "dmca/index.html",
    "legal-2257/index.html",
    "submit/index.html",
}
EXCLUDED_PREFIXES = ("category/", "blog/topic/")

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
SKIP_TAGS = {
    "table", "thead", "tbody", "tfoot", "tr", "ul", "ol", "script", "style",
    "svg", "nav", "noscript", "h1", "h2", "h3", "h4", "h5", "h6",
}
# Card grids, TOCs, and chrome. Not article prose.
SKIP_CLASSES = {
    "post-card", "post-list", "vip-grid", "vip-rich", "cards", "card",
    "side-toc", "m-toc",
}
SKIP_P_CLASSES = {
    "toc-h", "badge", "card-t", "score", "bar", "k", "info-kicker", "info-h",
    "info-sub", "g-row", "back-cat", "hero-eye",
}
# Never a sentence boundary, even when the next word is capitalized (names).
TITLE_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "gen", "sen",
    "rep", "gov",
}
# Not a boundary when the next word is lowercase or a number ("Inc. of", "No. 5").
# A capital after these still starts a sentence ("Bumble Inc. The same company").
SOFT_ABBREV = {
    "etc", "eg", "ie", "vs", "inc", "ltd", "co", "corp", "fig", "vol", "ave",
    "blvd", "rd", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "al", "am", "pm", "no", "phd", "us", "uk",
    "eu", "usa",
}
INLINE_BALANCE = {
    "em", "strong", "span", "b", "i", "small", "sup", "sub", "mark", "u", "s",
    "cite", "q", "abbr", "code", "time", "dfn", "kbd", "var", "bdi", "bdo",
    "data",
}
ENTITY_RE = re.compile(r"&(#x[0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
HREF_RE = re.compile(r"""(?i)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
TAG_LEAD_RE = re.compile(r"^/?\s*([A-Za-z][A-Za-z0-9:-]*)")


def class_list(tag: str) -> list[str]:
    m = re.search(r"""(?i)\bclass\s*=\s*(["'])(.*?)\1""", tag)
    if m:
        return m.group(2).split()
    m = re.search(r"""(?i)\bclass\s*=\s*([^\s>]+)""", tag)
    return m.group(1).split() if m else []


def tag_name(tag: str) -> str:
    inner = tag[1:-1].strip()
    if inner.endswith("/"):
        inner = inner[:-1].strip()
    m = TAG_LEAD_RE.match(inner)
    return m.group(1).lower() if m else ""


def is_end_tag(tag: str) -> bool:
    return tag.startswith("</")


def is_self_closing(tag: str, name: str) -> bool:
    return name in VOID_TAGS or tag.rstrip().endswith("/>")


def iter_tags(html: str, start: int = 0, end: int | None = None):
    """Yield (kind, tag_html, abs_start, abs_end) for tags, skipping raw script/style."""
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
            c = html[j]
            if quote:
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == ">":
                j += 1
                break
            j += 1
        else:
            break
        tok = html[lt:j]
        name = tag_name(tok)
        yield "tag", tok, lt, j
        if not is_end_tag(tok) and name in {"script", "style"}:
            closer = re.search(rf"(?i)</{name}\s*>", html[j:end])
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
            m = ENTITY_RE.match(text, i)
            if m:
                decoded = unescape(m.group(0))
                if not decoded:
                    decoded = m.group(0)
                for n, ch in enumerate(decoded):
                    # Multi-char entities are rare; keep the split point on the first char.
                    yield ch, html_offset + i if n == 0 else html_offset + i
                i = m.end()
                continue
        yield text[i], html_offset + i
        i += 1


def word_count(plain: str) -> int:
    return len(WORD_RE.findall(plain))


def is_fragment(plain: str) -> bool:
    """1–2 word lead-ins such as 'Yes.' or 'Sample bait.' are not their own paragraph."""
    stripped = plain.strip()
    if not stripped or stripped.endswith("?"):
        return False
    return word_count(stripped) <= 2


def abbrev_suppresses(visible: str, period_index: int, next_index: int) -> bool:
    """True when the period is an abbreviation, not a sentence end."""
    j = period_index - 1
    while j >= 0 and (visible[j].isalpha() or visible[j] == "."):
        j -= 1
    raw = visible[j + 1:period_index]
    if not raw:
        return False
    # Single initial: "J. Smith". A digit before the letter is a token
    # like "16K." or "24K.", which does end the sentence.
    if re.fullmatch(r"[A-Za-z]", raw):
        prev = visible[j] if j >= 0 else ""
        if prev.isdigit():
            return False
        return True
    letters = re.sub(r"[^A-Za-z]", "", raw).lower()
    if not letters:
        return False
    nxt = visible[next_index]
    next_is_lower_or_digit = nxt.islower() or nxt.isdigit()
    if letters in TITLE_ABBREV:
        return True
    # Dotted forms: U.S. e.g. i.e. a.m. p.m. Ph.D.
    if "." in raw or letters in SOFT_ABBREV:
        if letters in SOFT_ABBREV or "." in raw:
            return next_is_lower_or_digit
    return False


def find_sentences(inner: str):
    """Return sentence dicts with html spans into `inner`, or None if fewer than 3."""
    chars = []  # visible chars with source index and anchor depth / inline stack
    inline_stack: list[tuple[str, str]] = []
    anchor_depth = 0
    pos = 0
    tokens = list(iter_tags(inner))
    cursor = 0
    # Walk text and tags in order.
    pieces = []
    last = 0
    for kind, tok, start, end in tokens:
        if start > last:
            pieces.append(("text", inner[last:start], last))
        pieces.append(("tag", tok, start))
        last = end
    if last < len(inner):
        pieces.append(("text", inner[last:], last))

    for kind, tok, start in pieces:
        if kind == "text":
            for ch, html_i in decode_text(tok, start):
                chars.append((ch, html_i, anchor_depth, list(inline_stack)))
            continue
        if kind == "tag" and tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if is_end_tag(tok):
            if name == "a" and anchor_depth:
                anchor_depth -= 1
            if name in INLINE_BALANCE:
                for n in range(len(inline_stack) - 1, -1, -1):
                    if inline_stack[n][0] == name:
                        del inline_stack[n]
                        break
            continue
        if is_self_closing(tok, name):
            if name == "br":
                chars.append(("\n", end_of(tok, start), anchor_depth, list(inline_stack)))
            continue
        if name == "a":
            anchor_depth += 1
        if name in INLINE_BALANCE:
            inline_stack.append((name, tok))

    if not chars:
        return None
    visible = "".join(c[0] for c in chars)
    # Sentence content starts at the first non-space visible char.
    boundaries = []  # visible indexes where a new sentence starts
    i = 0
    n = len(visible)
    while i < n:
        ch = visible[i]
        if ch in ".!?":
            if ch == "." and i + 1 < n and visible[i + 1] == ".":
                i += 1
                continue
            if ch == "." and i > 0 and visible[i - 1].isdigit() and i + 1 < n and visible[i + 1].isdigit():
                i += 1
                continue
            j = i + 1
            while j < n and visible[j] in "\"'”’)]}":
                j += 1
            # "AdmireMe.VIP" and "SEGPAY.COM" have no space after the dot.
            # A real sentence boundary has whitespace before the next sentence.
            if j >= n or not visible[j].isspace():
                i += 1
                continue
            k = j
            while k < n and visible[k].isspace():
                k += 1
            if k >= n:
                break
            nxt = visible[k]
            if not (nxt.isupper() or nxt.isdigit() or nxt in "\"'“‘("):
                i += 1
                continue
            if abbrev_suppresses(visible, i, k):
                i += 1
                continue
            # Never split inside an anchor. The period and the next sentence
            # must not share an open <a>.
            if chars[i][2] > 0 and chars[k][2] > 0:
                i += 1
                continue
            boundaries.append(k)
            i = k
            continue
        i += 1

    starts = [0]
    # First content char may follow leading whitespace; sentence 0 starts at 0
    # of the visible string so leading markup stays with it.
    for b in boundaries:
        if b > starts[-1]:
            starts.append(b)
    if len(starts) < 3:
        return None

    sentences = []
    for idx, vis_start in enumerate(starts):
        vis_end = starts[idx + 1] if idx + 1 < len(starts) else n
        # Skip a leading whitespace-only "sentence" (should not happen).
        html_start = 0 if idx == 0 else chars[vis_start][1]
        if idx + 1 < len(starts):
            html_end = chars[starts[idx + 1]][1]
        else:
            html_end = len(inner)
        plain = visible[vis_start:vis_end].strip()
        # If html_start landed mid-entity (multi-char), snap back to entity start.
        sentences.append({
            "plain": plain,
            "html_start": html_start,
            "html_end": html_end,
            "fragment": is_fragment(plain),
            "inline_at_start": [] if idx == 0 else chars[vis_start][3],
            "anchor_at_start": 0 if idx == 0 else chars[vis_start][2],
        })
    # Drop empty plains
    sentences = [s for s in sentences if s["plain"]]
    if len(sentences) < 3:
        return None
    return sentences


def end_of(tok: str, start: int) -> int:
    return start + len(tok)


def pack_sentences(sentences: list[dict]) -> list[list[dict]]:
    """Glue 1–2 word fragments to a neighbor, then pack ~2 sentences per paragraph."""
    units: list[list[dict]] = []
    i = 0
    while i < len(sentences):
        if sentences[i]["fragment"] and i + 1 < len(sentences):
            units.append([sentences[i], sentences[i + 1]])
            i += 2
        else:
            units.append([sentences[i]])
            i += 1
    if len(units) >= 2 and len(units[-1]) == 1 and units[-1][0]["fragment"]:
        units[-2].extend(units.pop())

    paragraphs: list[list[dict]] = []
    cur: list[dict] = []
    cur_n = 0
    for unit in units:
        u_n = len(unit)
        if cur and (cur_n >= 2 or (cur_n + u_n > 2 and cur_n >= 1)):
            paragraphs.append(cur)
            cur = []
            cur_n = 0
        cur.extend(unit)
        cur_n += u_n
    if cur:
        paragraphs.append(cur)

    # Never leave a 1-word or 2-word fragment as its own paragraph.
    changed = True
    while changed and len(paragraphs) > 1:
        changed = False
        for i, para in enumerate(paragraphs):
            plain = " ".join(s["plain"] for s in para)
            if word_count(plain) <= 2:
                if i > 0:
                    paragraphs[i - 1].extend(paragraphs.pop(i))
                else:
                    paragraphs[1] = paragraphs[0] + paragraphs[1]
                    del paragraphs[0]
                changed = True
                break
    return paragraphs


def inline_open_at(inner: str, html_index: int) -> list[tuple[str, str]]:
    stack: list[tuple[str, str]] = []
    for kind, tok, start, end in iter_tags(inner, 0, html_index):
        if kind != "tag" or tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if is_end_tag(tok):
            if name in INLINE_BALANCE:
                for n in range(len(stack) - 1, -1, -1):
                    if stack[n][0] == name:
                        del stack[n]
                        break
            continue
        if is_self_closing(tok, name):
            continue
        if name in INLINE_BALANCE and end <= html_index:
            stack.append((name, tok))
    return stack


def balance_chunk(inner: str, chunk: str, html_start: int, html_end: int) -> str | None:
    """Close and reopen inline tags so the chunk is balanced. Never touch <a>."""
    if html_start > 0:
        # Confirm we are not inside an anchor.
        anchor = 0
        for kind, tok, start, end in iter_tags(inner, 0, html_start):
            if kind != "tag":
                continue
            name = tag_name(tok)
            if name != "a":
                continue
            if is_end_tag(tok):
                anchor = max(0, anchor - 1)
            elif not is_self_closing(tok, name):
                anchor += 1
        if anchor:
            return None
    open_at_start = inline_open_at(inner, html_start) if html_start else []
    # Tags opened inside the chunk and not closed stay open at the end.
    stack = list(open_at_start)
    for kind, tok, start, end in iter_tags(chunk):
        if kind != "tag" or tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if name == "a" and not is_end_tag(tok) and not is_self_closing(tok, name):
            # An anchor must be wholly inside the chunk. Track it and require close.
            pass
        if is_end_tag(tok):
            if name in INLINE_BALANCE:
                for n in range(len(stack) - 1, -1, -1):
                    if stack[n][0] == name:
                        del stack[n]
                        break
            continue
        if is_self_closing(tok, name):
            continue
        if name in INLINE_BALANCE:
            stack.append((name, tok))
    # stack is what remains open at the end. Close those.
    # Only close tags that were opened before the chunk or inside it and left open.
    closers = "".join(f"</{name}>" for name, _ in reversed(stack))
    openers = "".join(tok for _, tok in open_at_start)
    return openers + chunk + closers


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
                s = stack.pop()
                found.append(html[s:end])
        elif not is_self_closing(tok, name):
            stack.append(start)
    return found


def split_paragraph(full: str, indent: str) -> str | None:
    """Return replacement HTML for one <p>...</p>, or None to leave it."""
    m = re.match(r"(?is)<p\b[^>]*>", full)
    if not m or not re.search(r"(?is)</p\s*>$", full):
        return None
    open_tag = m.group(0)
    inner = full[m.end():full.lower().rfind("</p")]
    sentences = find_sentences(inner)
    if not sentences:
        return None
    groups = pack_sentences(sentences)
    if len(groups) < 2:
        return None
    pieces = []
    for gi, group in enumerate(groups):
        start = group[0]["html_start"]
        end = group[-1]["html_end"]
        chunk = inner[start:end]
        if gi != len(groups) - 1:
            chunk = chunk.rstrip(" \t\r\n")
        elif gi > 0:
            chunk = chunk.lstrip(" \t\r\n")
        balanced = balance_chunk(inner, chunk, start, end)
        if balanced is None or not balanced.strip():
            return None
        if "<a" in balanced.lower() or "</a" in balanced.lower():
            # Anchor must appear as a contiguous original substring.
            for anchor in anchors_in(balanced):
                if anchor not in inner and anchor not in full:
                    return None
        pieces.append(balanced)
    # Wording check inside the paragraph.
    def plain(s: str) -> str:
        text = re.sub(r"(?is)<[^>]+>", " ", s)
        return re.sub(r"\s+", " ", unescape(text)).strip()

    if plain(" ".join(pieces)) != plain(inner):
        return None
    # Anchors inside the paragraph stay intact and in order.
    if anchors_in("".join(pieces)) != anchors_in(inner):
        return None
    sep = "\n" + indent
    return sep.join(f"{open_tag}{piece}</p>" for piece in pieces)


def should_split(stack: list[tuple[str, set[str]]], p_tag: str) -> bool:
    if not any(name == "main" for name, _ in stack):
        return False
    if not any(name == "article" for name, _ in stack):
        return False
    for name, classes in stack:
        if name in SKIP_TAGS:
            return False
        if SKIP_CLASSES.intersection(classes):
            return False
    if SKIP_P_CLASSES.intersection(class_list(p_tag)):
        return False
    return True


def transform_html(html: str) -> tuple[str, int]:
    """Split qualifying paragraphs. Returns (new_html, paragraphs_split)."""
    out = []
    cursor = 0
    stack: list[tuple[str, set[str]]] = []
    split_count = 0
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
        # iter_tags swallows script/style bodies, including the closing tag.
        if name in {"script", "style"}:
            continue
        if name == "p" and not is_self_closing(tok, name) and should_split(stack, tok):
            close = re.search(r"(?i)</p\s*>", html[end:])
            if not close:
                continue
            # Another <p> before </p> means the markup is not a clean paragraph.
            nxt = re.search(r"(?i)<p\b", html[end:end + close.start()])
            if nxt:
                continue
            full_end = end + close.end()
            full = html[start:full_end]
            indent = line_indent(html, start)
            replacement = split_paragraph(full, indent)
            if replacement and replacement != full:
                out.append(html[cursor:start])
                out.append(replacement)
                cursor = full_end
                split_count += 1
            continue
        if not is_self_closing(tok, name):
            stack.append((name, set(class_list(tok))))
    out.append(html[cursor:])
    return "".join(out), split_count


def normalized_text(html: str) -> str:
    no_script = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    no_tags = re.sub(r"(?is)<[^>]+>", " ", no_script)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def hrefs(html: str) -> list[str]:
    return [a or b or c or "" for a, b, c in HREF_RE.findall(html)]


def json_ld_blocks(html: str) -> list[str]:
    return re.findall(r"(?is)<script\s+type=[\"']application/ld\+json[\"']\s*>.*?</script>", html)


def tag_balance_ok(html: str) -> bool:
    stack = []
    for kind, tok, start, end in iter_tags(html):
        if kind != "tag" or tok.startswith("<!--"):
            continue
        name = tag_name(tok)
        if not name or name.startswith("!") or "?" in name:
            continue
        if is_end_tag(tok):
            if name in VOID_TAGS:
                continue
            if not stack or stack[-1] != name:
                # Pop forward to a match if a void-like miss happened; otherwise fail.
                if name in stack:
                    while stack and stack[-1] != name:
                        stack.pop()
                    if stack and stack[-1] == name:
                        stack.pop()
                        continue
                return False
            stack.pop()
        elif not is_self_closing(tok, name):
            stack.append(name)
    return not stack


def validate(before: str, after: str) -> list[str]:
    problems = []
    if normalized_text(before) != normalized_text(after):
        problems.append("visible wording changed")
    if hrefs(before) != hrefs(after):
        problems.append("href list changed")
    if anchors_in(before) != anchors_in(after):
        problems.append("anchor elements changed")
    if json_ld_blocks(before) != json_ld_blocks(after):
        problems.append("JSON-LD changed")
    if before.count("<a") != after.count("<a") or before.lower().count("</a>") != after.lower().count("</a>"):
        problems.append("anchor tag count changed")
    if not tag_balance_ok(after):
        problems.append("tag balance broken")
    return problems


def is_article_page(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if path.name != "index.html":
        return False
    if rel in EXCLUDED_REL or rel.startswith(EXCLUDED_PREFIXES):
        return False
    if any(part in {"assets", "node_modules", ".git"} for part in path.parts):
        return False
    text = path.read_text(encoding="utf-8")
    return "<article" in text.lower()


def header_footer_slice(html: str) -> str | None:
    """Client-nav JSON stores the document from <header> through </footer>."""
    start = html.find("<header")
    end = html.rfind("</footer>")
    if start < 0 or end < 0:
        return None
    return html[start:end + len("</footer>")]


def json_path_for(html_path: Path) -> Path | None:
    rel = html_path.relative_to(ROOT)
    if rel.name != "index.html":
        return None
    jp = ROOT / "assets" / "pages" / f"{rel.parent.as_posix()}.json"
    return jp if jp.exists() else None


def self_test() -> None:
    cases = [
        (
            "<p>Alpha sentence here. Beta sentence here. Gamma sentence here.</p>",
            ["Alpha sentence here. Beta sentence here.", "Gamma sentence here."],
        ),
        (
            "<p>One here. Two here. Three here. Four here.</p>",
            ["One here. Two here.", "Three here. Four here."],
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
            "<p>It costs $4.99 today. Then it renews at full price. After that you can cancel.</p>",
            [
                "It costs $4.99 today. Then it renews at full price.",
                "After that you can cancel.",
            ],
        ),
        (
            "<p>Premium was $14.99 and 16K. Luxe was $39.99 a year. Elite was $89.99 and 24K memory.</p>",
            [
                "Premium was $14.99 and 16K. Luxe was $39.99 a year.",
                "Elite was $89.99 and 24K memory.",
            ],
        ),
        (
            "<p>The descriptor is SEGPAY.COM*FeetFinder on a statement. Anyone who reads it can see the name. Keep the card somewhere private.</p>",
            [
                "The descriptor is SEGPAY.COM*FeetFinder on a statement. Anyone who reads it can see the name.",
                "Keep the card somewhere private.",
            ],
        ),
        (
            "<p>A regional site such as AdmireMe.VIP may suit you. Global sites are louder. Pick the audience you can actually reach.</p>",
            [
                "A regional site such as AdmireMe.VIP may suit you. Global sites are louder.",
                "Pick the audience you can actually reach.",
            ],
        ),
        (
            "<p>Sample bait. A buyer asks for free samples and then disappears. Some scammers build a library.</p>",
            [
                "Sample bait. A buyer asks for free samples and then disappears.",
                "Some scammers build a library.",
            ],
        ),
        (
            '<p class="disclosure"><em>Disclosure: Dark-Ero is independent. We have no deal with the site and this page has no affiliate link. Adults 18+ only.</em></p>',
            [
                "Disclosure: Dark-Ero is independent. We have no deal with the site and this page has no affiliate link.",
                "Adults 18+ only.",
            ],
        ),
        (
            '<p>Read the <a href="https://example.com/review">full review. It keeps going</a> after the link. Second sentence stands alone. Third sentence ends it.</p>',
            None,  # checked structurally below
        ),
    ]
    for src, expected in cases:
        wrapped = f"<main><article>{src}</article></main>"
        out, n = transform_html(wrapped)
        problems = validate(wrapped, out)
        if problems:
            raise SystemExit(f"self-test validate failed for {src[:60]}: {problems}")
        if expected is None and "full review" in src:
            if anchors_in(out) != anchors_in(wrapped):
                raise SystemExit("self-test split an anchor")
            if out.count("<p") < 2:
                raise SystemExit(f"self-test did not split linked paragraph:\n{out}")
            continue
        if expected is None:
            if n != 0:
                raise SystemExit(f"self-test unexpectedly split:\n{src}\n->\n{out}")
            continue
        if n != 1:
            raise SystemExit(f"self-test split count {n} for {src}\n{out}")
        plains = []
        for m in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", out):
            text = re.sub(r"(?is)<[^>]+>", " ", m.group(1))
            plains.append(re.sub(r"\s+", " ", unescape(text)).strip())
        if plains != expected:
            raise SystemExit(f"self-test mismatch\n got {plains}\n want {expected}")
    # Idempotent
    sample = "<main><article><p>One here. Two here. Three here. Four here.</p></article></main>"
    once, _ = transform_html(sample)
    twice, n2 = transform_html(once)
    if twice != once or n2 != 0:
        raise SystemExit("self-test is not idempotent")
    print("self-test ok")


def article_pages() -> list[Path]:
    pages = []
    for path in sorted(ROOT.rglob("index.html")):
        if is_article_page(path):
            pages.append(path)
    return pages


def process(write: bool) -> dict:
    pages = article_pages()
    stats = {
        "pages_scanned": len(pages),
        "pages_changed": 0,
        "paragraphs_split": 0,
        "paragraphs_added": 0,
        "json_updated": 0,
        "json_missing": 0,
        "skipped_invalid": [],
    }
    for path in pages:
        original = path.read_text(encoding="utf-8")
        updated, nsplit = transform_html(original)
        problems = validate(original, updated)
        if problems:
            stats["skipped_invalid"].append(f"{path.relative_to(ROOT)}: {', '.join(problems)}")
            continue
        added = updated.count("<p") - original.count("<p")
        # JSON copy, if this page has one. The body is the header-to-footer
        # slice of the HTML, so client-nav shows the same paragraphs.
        jp = json_path_for(path)
        json_updated = None
        if jp is not None:
            json_original = jp.read_text(encoding="utf-8")
            data = json.loads(json_original)
            sliced = header_footer_slice(updated)
            if isinstance(data, dict) and isinstance(data.get("body"), str) and sliced is not None:
                new_body = sliced
                if data["body"].endswith("\n") and not new_body.endswith("\n"):
                    new_body += "\n"
                if new_body != data["body"]:
                    # Paragraph breaks come from the HTML. A stale copy also
                    # picks up wording that is already on the live page.
                    data["body"] = new_body
                    json_updated = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                    if json_original.endswith("\n"):
                        json_updated += "\n"
        elif path.relative_to(ROOT).parts[:1] == ("blog",):
            stats["json_missing"] += 1

        if nsplit:
            stats["pages_changed"] += 1
            stats["paragraphs_split"] += nsplit
            stats["paragraphs_added"] += added
        if write and updated != original:
            path.write_text(updated, encoding="utf-8")
        if json_updated is not None:
            stats["json_updated"] += 1
            if write:
                jp.write_text(json_updated, encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write HTML and JSON files")
    args = parser.parse_args()
    self_test()
    stats = process(write=args.write)
    print(json.dumps(stats, indent=2))
    if stats["skipped_invalid"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
