"""Cuts a streamed reply into sentences so each one can be sent to TTS as soon as it is complete.

Text is only ever split and trimmed at the ends: it is never translated, transliterated or rewritten. Pieces that
contain no letter or digit at all (a lone "!" left over from "?!", for example) have nothing to speak and are dropped.

Boundaries:
- `!`, `?`, `।`, `॥` and a newline end a sentence immediately (together with any closing quotes already received).
- `.` and `…` need one more character of look-ahead, so "3.5", "a.b" and "e.g.x" are not split, and a few
  abbreviations ("Dr.", "Mr.", "e.g.", an initial like "A.") are not treated as sentence ends.
- A sentence that grows past `max_chars` without a boundary is split at a clause mark or a space (a hard cut only if
  there is no space), so one very long sentence cannot delay the first audio or exceed a TTS text limit.
"""

import re

_TERMINATORS = ".!?।॥…"
_UNAMBIGUOUS = "!?।॥"  # end a sentence even when they are the last character received so far
_CLOSERS = "\"')]}»”’"
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "e.g", "i.e"}
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)$")


def _speakable(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _is_abbreviation(buffer: str, dot_index: int) -> bool:
    match = _LAST_WORD.search(buffer[:dot_index])
    if match is None:
        return False
    word = match.group(1)
    before = buffer[: match.start()]
    if len(word) == 1 and word.isupper() and (not before or before[-1].isspace()):
        return True  # an initial such as "A. Kumar"
    return word.lower() in _ABBREVIATIONS


class SentenceChunker:
    def __init__(self, max_chars: int = 300) -> None:
        if max_chars < 20:
            raise ValueError("max_chars must be at least 20")
        self._max = max_chars
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text and return every sentence that is now complete (in order)."""
        self._buffer += text
        return self._drain(final=False)

    def flush(self) -> list[str]:
        """The stream ended: return whatever is left as the last sentence(s)."""
        return self._drain(final=True)

    # ------------------------------------------------------------------ internals

    def _drain(self, *, final: bool) -> list[str]:
        out: list[str] = []
        while True:
            end = self._boundary(final)
            if end is None:
                break
            self._emit(self._buffer[:end], out)
            self._buffer = self._buffer[end:]
        while len(self._buffer.strip()) > self._max:  # a long sentence with no boundary yet
            piece, self._buffer = self._split(self._buffer.lstrip())
            self._emit(piece, out)
        if final:
            self._emit(self._buffer, out)
            self._buffer = ""
        return out

    def _boundary(self, final: bool) -> int | None:
        buf = self._buffer
        n = len(buf)
        i = 0
        while i < n:
            ch = buf[i]
            if ch == "\n":
                return i + 1
            if ch in _TERMINATORS:
                j = i + 1
                while j < n and (buf[j] in _TERMINATORS or buf[j] in _CLOSERS):
                    j += 1
                if ch not in _UNAMBIGUOUS:
                    if j >= n:
                        if not final:
                            return None  # wait for the next character: it may turn "3." into "3.5"
                    elif not buf[j].isspace() or (ch == "." and _is_abbreviation(buf, i)):
                        i = j
                        continue
                return j
            i += 1
        return None

    def _emit(self, piece: str, out: list[str]) -> None:
        piece = piece.strip()
        while len(piece) > self._max:
            head, piece = self._split(piece)
            self._emit_one(head, out)
            piece = piece.strip()
        self._emit_one(piece, out)

    @staticmethod
    def _emit_one(piece: str, out: list[str]) -> None:
        piece = piece.strip()
        if piece and _speakable(piece):
            out.append(piece)

    def _split(self, text: str) -> tuple[str, str]:
        """Cut `text` (longer than max_chars) into a head of at most max_chars and the rest."""
        window = text[: self._max]
        cut = max((window.rfind(mark + " ") + 1 for mark in ",;:"), default=0)
        if cut < self._max // 2:
            cut = window.rfind(" ") + 1  # last space; the head keeps no trailing space after strip
        if cut <= 0:
            cut = self._max  # no space at all: hard cut
        return text[:cut], text[cut:]
