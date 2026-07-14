from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag in {"br", "p", "div", "li", "tr", "table", "section", "article", "header", "footer"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in {"p", "div", "li", "tr", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self._skip_depth and data:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


_TAG_RE = re.compile(r"<[A-Za-z][^>]*>|</[A-Za-z][^>]*>|&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")


def normalize_text_for_embedding(text: str) -> str:
    value = str(text or "")
    if _looks_like_html(value):
        parser = _TextExtractor()
        try:
            parser.feed(value)
            value = parser.text()
        except Exception:
            value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\x00", " ")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[^\S\n]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _looks_like_html(text: str) -> bool:
    if not text:
        return False
    sample = text[:20000]
    if "<html" in sample.lower() or "<body" in sample.lower() or "<div" in sample.lower() or "<span" in sample.lower():
        return True
    return bool(_TAG_RE.search(sample))
