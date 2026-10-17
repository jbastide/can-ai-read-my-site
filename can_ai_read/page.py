"""Read a page the way an AI crawler that does not run JavaScript reads it."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
SKIP = {"script", "style", "template", "svg", "math", "head"}
BLOCK = {
    "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section",
    "article", "header", "footer", "main", "nav", "aside", "table", "ul", "ol", "dl", "dt",
    "dd", "blockquote", "br", "hr", "figcaption", "caption", "summary", "details", "form",
}

_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden)", re.I)


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, hidden, skip)
        self.visible = []
        self.hidden = []
        self.title = ""
        self._in_title = False
        self.lang = ""
        self.meta_description = ""
        self.canonical = ""
        self.headings = []  # (level, text)
        self._heading = None
        self.tables = 0
        self.tables_with_th = 0
        self._table_has_th = []
        self.scripts = 0
        self.script_srcs = 0
        self.inline_script_chars = 0
        self.jsonld = []
        self._script_type = None
        self._script_buf = []

    def _state(self):
        hidden = any(h for _, h, _ in self.stack)
        skip = any(s for _, _, s in self.stack)
        return hidden, skip

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        if tag == "meta" and a.get("name", "").lower() == "description":
            self.meta_description = a.get("content", "").strip()
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href", "")
        if tag == "title":
            self._in_title = True
        if tag == "script":
            self.scripts += 1
            if a.get("src"):
                self.script_srcs += 1
            self._script_type = a.get("type", "").lower()
            self._script_buf = []
        if tag == "table":
            self.tables += 1
            self._table_has_th.append(False)
        if tag == "th" and self._table_has_th:
            self._table_has_th[-1] = True
        if tag in ("h1", "h2", "h3"):
            self._heading = [int(tag[1]), []]
        if tag in BLOCK:
            self.visible.append("\n")
        if tag in VOID:
            return
        hidden = (
            "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or bool(_HIDDEN_STYLE.search(a.get("style", "")))
        )
        self.stack.append((tag, hidden, tag in SKIP))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script":
            if "ld+json" in (self._script_type or ""):
                self.jsonld.append("".join(self._script_buf))
            else:
                self.inline_script_chars += sum(len(x) for x in self._script_buf)
            self._script_type = None
            self._script_buf = []
        if tag == "table" and self._table_has_th:
            if self._table_has_th.pop():
                self.tables_with_th += 1
        if tag in ("h1", "h2", "h3") and self._heading and self._heading[0] == int(tag[1]):
            text = " ".join("".join(self._heading[1]).split())
            if text:
                self.headings.append((self._heading[0], text))
            self._heading = None
        if tag in BLOCK:
            self.visible.append("\n")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._script_type is not None:
            self._script_buf.append(data)
            return
        if self._in_title:
            self.title += data
            return
        hidden, skip = self._state()
        if skip:
            return
        if self._heading is not None and not hidden:
            self._heading[1].append(data)
        (self.hidden if hidden else self.visible).append(data)


_CURRENCY = r"(?:\$|€|£|USD|SEK|EUR|GBP|NOK|DKK|kr\.?|kronor)"
_AMOUNT = r"\d[\d,.  ]*\d|\d"
PRICE_RE = re.compile(
    rf"(?:{_CURRENCY}\s?(?:{_AMOUNT}))|(?:(?:{_AMOUNT})\s?{_CURRENCY})(?![A-Za-z])", re.I
)
_MONTHS_EN = "january|february|march|april|may|june|july|august|september|october|november|december"
_MONTHS_SV = "januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december"
DATE_RE = re.compile(
    rf"\b20\d\d-\d\d-\d\d\b"
    rf"|\b(?:{_MONTHS_EN})\.? \d{{1,2}},? 20\d\d\b"
    rf"|\b\d{{1,2}} (?:{_MONTHS_EN}|{_MONTHS_SV}) 20\d\d\b"
    rf"|\b(?:{_MONTHS_EN}|{_MONTHS_SV}) 20\d\d\b",
    re.I,
)
UPDATED_RE = re.compile(r"(last updated|updated on|updated:|last modified|senast uppdaterad|uppdaterad)", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _walk_prices(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("price", "lowPrice", "highPrice") and isinstance(v, (str, int, float)):
                out.append(str(v))
            else:
                _walk_prices(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_prices(item, out)


def _digits(s: str) -> str:
    whole = re.split(r"[.,](?=\d{1,2}$)", s.strip())[0]
    return re.sub(r"\D", "", whole)


def read(html: str) -> dict:
    r = _Reader()
    try:
        r.feed(html)
        r.close()
    except Exception:  # noqa: BLE001 - a broken page should still give a partial reading
        pass
    visible = re.sub(r"[ \t\r\f\v]+", " ", "".join(r.visible))
    visible = re.sub(r"\n\s*\n+", "\n", visible).strip()
    hidden = " ".join("".join(r.hidden).split())
    words = _words(visible)

    jsonld_prices = []
    date_modified = ""
    for block in r.jsonld:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        _walk_prices(data, jsonld_prices)
        m = re.search(r'"dateModified"\s*:\s*"([^"]+)"', block)
        if m:
            date_modified = m.group(1)

    visible_digits = {_digits(p) for p in PRICE_RE.findall(visible)}
    visible_numbers = {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d,.  ]*", visible)}
    only_in_code = []
    for p in jsonld_prices:
        d = _digits(p)
        if d and d not in visible_digits and d not in visible_numbers:
            only_in_code.append(p)

    h2s = [t for lvl, t in r.headings if lvl == 2]
    looks_like_app = words < 150 and r.scripts >= 3

    return {
        "title": " ".join(r.title.split()),
        "lang": r.lang,
        "meta_description": r.meta_description,
        "canonical": r.canonical,
        "words": words,
        "hidden_words": _words(hidden),
        "h1": [t for lvl, t in r.headings if lvl == 1],
        "h2": h2s,
        "question_headings": sum(1 for t in h2s if t.rstrip().endswith("?")),
        "tables": r.tables,
        "tables_with_headers": r.tables_with_th,
        "scripts": r.scripts,
        "external_scripts": r.script_srcs,
        "inline_script_chars": r.inline_script_chars,
        "looks_like_js_app": looks_like_app,
        "prices": sorted({p.strip() for p in PRICE_RE.findall(visible)})[:20],
        "dates": sorted({d for d in DATE_RE.findall(visible)})[:20],
        "has_updated_label": bool(UPDATED_RE.search(visible)),
        "jsonld_blocks": len(r.jsonld),
        "jsonld_prices": jsonld_prices[:20],
        "prices_only_in_code": only_in_code[:20],
        "date_modified": date_modified,
        "text": visible,
    }
