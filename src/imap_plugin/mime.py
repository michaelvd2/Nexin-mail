from __future__ import annotations

import html
import json
import re
from email.header import decode_header
from email.message import Message
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
REMOTE_RE = re.compile(r"(?i)(?:src|href)\s*=\s*['\"](?:https?:|//)[^'\"]*['\"]")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
ANCHOR_RE = re.compile(r"(?is)<a\b[^>]*?href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>")
IMAGE_SRC_RE = re.compile(r"(?is)<img\b[^>]*?src\s*=\s*['\"]([^'\"]+)['\"]")
URL_RE = re.compile(r"(?i)https?://[^\s<>\"']+")
UNSUBSCRIBE_TEXT_RE = re.compile(
    r"(?i)\b(?:unsubscribe|afmelden|uitschrijven|opt[ -]?out|stop receiving|"
    r"e-?mailvoorkeuren|mailvoorkeuren)\b"
)

SAFE_BODY_TAGS = {
    "p", "div", "span", "br", "strong", "b", "em", "i", "u", "s", "del",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
    "pre", "code", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "hr",
}
VOID_BODY_TAGS = {"br", "hr"}
BLOCKED_CONTENT_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "canvas", "form", "button", "input", "textarea", "select", "video", "audio", "meta", "link", "base"}


class _SafeBodyParser(HTMLParser):
    """Turn hostile HTML into a small semantic tree without retaining attributes or URLs."""

    def __init__(self, max_nodes: int = 5000, max_depth: int = 40) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[dict[str, Any]] = []
        self._containers: list[list[dict[str, Any]]] = [self.root]
        self._open: list[tuple[str, bool]] = []
        self._blocked_depth = 0
        self._nodes = 0
        self._max_nodes = max_nodes
        self._max_depth = max_depth
        self._remote_image_index = 0

    def _append(self, node: dict[str, Any]) -> bool:
        if self._nodes >= self._max_nodes:
            return False
        self._nodes += 1
        self._containers[-1].append(node)
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self._blocked_depth:
            if tag in BLOCKED_CONTENT_TAGS:
                self._blocked_depth += 1
            return
        if tag in BLOCKED_CONTENT_TAGS:
            self._blocked_depth = 1
            return
        if tag == "img":
            source = next((value for key, value in attrs if key.casefold() == "src" and value), "")
            node: dict[str, Any] = {"type": "blocked_image"}
            if html.unescape(source).strip().casefold().startswith("https://"):
                node["remote_image_index"] = self._remote_image_index
                self._remote_image_index += 1
            self._append(node)
            return
        rendered = "link" if tag == "a" else tag
        if rendered not in SAFE_BODY_TAGS and rendered != "link":
            self._open.append((tag, False))
            return
        node: dict[str, Any] = {"type": "element", "tag": rendered, "children": []}
        if not self._append(node):
            return
        pushed = tag not in VOID_BODY_TAGS and len(self._containers) < self._max_depth
        self._open.append((tag, pushed))
        if pushed:
            self._containers.append(node["children"])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._blocked_depth:
            if tag in BLOCKED_CONTENT_TAGS:
                self._blocked_depth -= 1
            return
        for index in range(len(self._open) - 1, -1, -1):
            open_tag, _ = self._open[index]
            if open_tag != tag:
                continue
            closing = self._open[index:]
            del self._open[index:]
            for _, pushed in reversed(closing):
                if pushed and len(self._containers) > 1:
                    self._containers.pop()
            break

    def handle_data(self, data: str) -> None:
        if self._blocked_depth or not data:
            return
        self._append({"type": "text", "text": data})


def safe_html_nodes(value: str) -> list[dict[str, Any]]:
    parser = _SafeBodyParser()
    parser.feed(value)
    parser.close()
    return parser.root


def decode_value(value: str | None) -> str:
    if not value:
        return ""
    pieces: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            pieces.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            pieces.append(part)
    return "".join(pieces)


def html_to_text(value: str) -> str:
    value = SCRIPT_RE.sub(" ", value)
    value = REMOTE_RE.sub("", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", value)
    value = TAG_RE.sub(" ", value)
    value = html.unescape(value)
    lines = [SPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def decoded_text(message: Message, ceiling: int) -> tuple[str, bool]:
    chunks: list[str] = []
    total = 0
    candidates = list(message.walk()) if message.is_multipart() else [message]
    plain_found = any(part.get_content_type() == "text/plain" for part in candidates)
    for part in candidates:
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        if ctype not in ({"text/plain"} if plain_found else {"text/html"}):
            continue
        raw = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        value = raw.decode(charset, errors="replace")
        if ctype == "text/html":
            value = html_to_text(value)
        total += len(value.encode("utf-8"))
        if total > ceiling:
            return "", True
        chunks.append(value)
    return "\n\n".join(chunks).strip(), False


def decoded_body(message: Message, ceiling: int) -> tuple[str, list[dict[str, Any]] | None, bool]:
    """Return readable text plus a URL-free semantic rendering tree for HTML mail."""
    text, oversized = decoded_text(message, ceiling)
    if oversized:
        return "", None, True
    candidates = list(message.walk()) if message.is_multipart() else [message]
    html_part = next((
        part for part in candidates
        if part.get_content_type() == "text/html" and part.get_content_disposition() != "attachment"
    ), None)
    if html_part is None:
        return text, None, False
    raw = html_part.get_payload(decode=True) or b""
    value = raw.decode(html_part.get_content_charset() or "utf-8", errors="replace")
    nodes = safe_html_nodes(value)
    response_size = len(text.encode("utf-8")) + len(json.dumps(nodes, ensure_ascii=False).encode("utf-8"))
    if response_size > ceiling:
        return "", None, True
    return text, nodes, False


def _trusted_authentication_results(message: Message, trusted_authserv_ids: tuple[str, ...]) -> tuple[str, bool]:
    trusted = {value.casefold().rstrip(".") for value in trusted_authserv_ids}
    accepted: list[str] = []
    observed = False
    for value in message.get_all("Authentication-Results", []):
        decoded = decode_value(value)[:4000]
        observed = True
        authserv_id = decoded.split(";", 1)[0].strip().casefold().rstrip(".")
        if authserv_id in trusted:
            accepted.append(decoded)
    return "\n".join(accepted)[:4000], observed


def security_signals(message: Message, trusted_authserv_ids: tuple[str, ...] = ()) -> dict[str, object]:
    """Extract bounded, inert security metadata without opening URLs or attachments."""
    authentication, authentication_observed = _trusted_authentication_results(
        message, trusted_authserv_ids
    )
    reply_to = decode_value(message.get("Reply-To"))[:1000]
    list_unsubscribe = decode_value(message.get("List-Unsubscribe"))[:4000]
    list_post = decode_value(message.get("List-Unsubscribe-Post"))[:1000]
    list_id = decode_value(message.get("List-ID"))[:500]
    https_urls: list[str] = []
    body_unsubscribe_urls: list[str] = []
    remote_image_urls: list[str] = []
    mailto = False
    for match in re.findall(r"<([^>]+)>", list_unsubscribe):
        candidate = match.strip()
        if candidate.casefold().startswith("https://"):
            https_urls.append(candidate[:2048])
        elif candidate.casefold().startswith("mailto:"):
            mailto = True

    remote_count = 0
    mismatch_count = 0
    remote_image_source_selected = False
    for part in (list(message.walk()) if message.is_multipart() else [message]):
        if part.get_content_type() != "text/html" or part.get_content_disposition() == "attachment":
            continue
        raw = part.get_payload(decode=True) or b""
        value = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        remote_count += min(100, len(URL_RE.findall(value)))
        if not remote_image_source_selected:
            remote_image_source_selected = True
            for source in IMAGE_SRC_RE.findall(value):
                candidate = html.unescape(source).strip()
                if candidate.casefold().startswith("https://"):
                    remote_image_urls.append(candidate[:2048])
                if len(remote_image_urls) >= 10:
                    break
        for destination, visible_html in ANCHOR_RE.findall(value)[:50]:
            visible = html_to_text(visible_html).strip()
            candidate = html.unescape(destination).strip()
            if (
                UNSUBSCRIBE_TEXT_RE.search(visible)
                and candidate.casefold().startswith("https://")
                and candidate not in body_unsubscribe_urls
            ):
                body_unsubscribe_urls.append(candidate[:2048])
            if not visible.casefold().startswith(("http://", "https://")):
                continue
            visible_host = (urlparse(visible).hostname or "").casefold()
            destination_host = (urlparse(destination).hostname or "").casefold()
            if visible_host and destination_host and visible_host != destination_host:
                mismatch_count += 1
    return {
        "authentication": authentication,
        "authentication_observed": authentication_observed,
        "authentication_trusted": bool(authentication),
        "reply_to": reply_to,
        "remote_url_count": min(remote_count, 100),
        "link_mismatch_count": min(mismatch_count, 50),
        "list_unsubscribe_https": https_urls[:3],
        "body_unsubscribe_https": body_unsubscribe_urls[:3],
        "remote_image_https": remote_image_urls[:10],
        "list_unsubscribe_mailto": mailto,
        "list_unsubscribe_one_click": "list-unsubscribe=one-click" in list_post.casefold(),
        "list_id": list_id,
        "has_attachments": any(part.get_content_disposition() == "attachment" or part.get_filename() for part in message.walk()),
    }
