"""Turn agent markdown into text a chat channel renders correctly.

WeChat Official Account text messages are plain text: ``**bold**`` shows its
asterisks, ``#`` headings show their hashes, and tables collapse into unreadable
pipes. Emoji and newlines do render, so the goal is to keep structure legible
while removing markup the channel will not interpret.

Streaming needs a second job from this module: cutting accumulated text at
places a reader expects a message to end, so a streamed reply arrives as whole
sentences instead of fragments.
"""

from __future__ import annotations

import re


# Inline markup that carries no meaning once the markers are visible.
_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_UNORDERED_ITEM = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_ORDERED_ITEM = re.compile(r"^(\s*)(\d{1,2})[.)]\s+", re.MULTILINE)
_LINK = re.compile(r"\[([^\]\n]*)\]\(\s*<?([^\s)]+)>?[^)]*\)")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*<?([^\s)]+)>?[^)]*\)")
_FENCE = re.compile(r"^\s*```[^\n]*$", re.MULTILINE)
_HORIZONTAL_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)
_TABLE_DIVIDER = re.compile(r"\s*\|?[\s:-]*\|[\s:|-]*")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)

BULLET = "·"
# Sentence-ish boundaries a reader accepts as the end of a chat bubble.
_BOUNDARY_CHARS = "。！？!?；;\n"


def _table_row_to_text(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return " | ".join(cell for cell in cells if cell)


def to_plain_text(value: str) -> str:
    """Render markdown as plain text without dropping information.

    Links keep both the label and the URL because a customer may need to open
    it, and the channel makes bare URLs tappable. Emoji and other non-ASCII
    characters pass through untouched.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE.sub("", text)
    text = _IMAGE.sub(lambda m: (m.group(1) or "图片").strip(), text)
    text = _LINK.sub(lambda m: f"{(m.group(1) or '').strip()} {m.group(2).strip()}".strip(), text)
    text = _INLINE_CODE.sub(lambda m: m.group(1), text)
    text = _BOLD_ITALIC.sub(lambda m: m.group(2), text)
    text = _HEADING.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _HORIZONTAL_RULE.sub("", text)
    # Drop divider rows outright: blanking them would leave a stray empty line
    # in the middle of the table.
    text = "\n".join(
        _table_row_to_text(line) if line.strip().startswith("|") else line
        for line in text.split("\n")
        if not _TABLE_DIVIDER.fullmatch(line)
    )
    text = _ORDERED_ITEM.sub(lambda m: f"{m.group(1)}{m.group(2)}. ", text)
    text = _UNORDERED_ITEM.sub(lambda m: f"{m.group(1)}{BULLET} ", text)
    text = _TRAILING_SPACES.sub("", text)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def split_at_boundary(buffer: str, *, min_chars: int, max_chars: int) -> tuple[str, str]:
    """Split a streaming buffer into one sendable chunk and the remainder.

    Returns an empty chunk when the buffer is not yet worth sending. Waiting for
    a sentence end keeps a streamed reply readable, while ``max_chars`` stops a
    run-on paragraph from growing past what the channel accepts.
    """
    if not isinstance(buffer, str) or not buffer:
        return "", ""
    if len(buffer) >= max_chars:
        cut = _last_boundary(buffer[:max_chars])
        if cut <= 0:
            cut = max_chars
        return buffer[:cut], buffer[cut:]
    if len(buffer) < min_chars:
        return "", buffer
    cut = _last_boundary(buffer)
    if cut <= 0:
        return "", buffer
    return buffer[:cut], buffer[cut:]


def _last_boundary(value: str) -> int:
    """Return the index just past the last sentence boundary, or 0."""
    best = 0
    for index, char in enumerate(value):
        if char in _BOUNDARY_CHARS:
            best = index + 1
    return best
