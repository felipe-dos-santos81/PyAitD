# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class BookToken:
    kind: str
    text: str = ""


def parse_system_texts(raw):
    out = {}
    for line in raw.decode("cp437").replace("\r\n", "\n").splitlines():
        match = re.fullmatch(r"@(\d+):(.*)", line)
        if match:
            out[int(match.group(1))] = match.group(2)
    return out


def parse_book_tokens(raw):
    text = raw.split(b"\x1a", 1)[0].decode("cp437").replace("\r\n", "\n")
    controls = {"P": "page", "T": "tab", "C": "center", "G": "number"}
    tokens = []
    plain = []

    def flush():
        if plain:
            tokens.append(BookToken("text", "".join(plain)))
            plain.clear()

    i = 0
    while i < len(text):
        if text[i] == "#" and i + 1 < len(text) and text[i + 1] in controls:
            flush()
            kind = controls[text[i + 1]]
            i += 2
            if kind == "number":
                start = i
                while i < len(text) and text[i].isdigit():
                    i += 1
                tokens.append(BookToken(kind, text[start:i]))
            else:
                tokens.append(BookToken(kind))
            continue
        plain.append(text[i])
        i += 1
    flush()
    return tuple(tokens)
