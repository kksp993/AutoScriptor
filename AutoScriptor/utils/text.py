"""Small, device-independent post-processors for scalar OCR text."""

import re


def _match_edge_text(text: str, pattern: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"Expected OCR text, got {type(text).__name__}")
    matched = re.search(pattern, text.strip())
    if matched is None or not (result := matched.group().strip()):
        raise ValueError(f"OCR text does not match {pattern!r}: {text!r}")
    return result


def pretext(text: str) -> str:
    """Return the leading non-digit run, with surrounding whitespace removed."""
    return _match_edge_text(text, r"^\D+")


def posttext(text: str) -> str:
    """Return the trailing non-digit run, with surrounding whitespace removed."""
    return _match_edge_text(text, r"\D+$")


def prenum(text: str) -> int:
    """Return the leading unsigned integer, ignoring surrounding whitespace."""
    return int(_match_edge_text(text, r"^\d+"))


def postnum(text: str) -> int:
    """Return the trailing unsigned integer, ignoring surrounding whitespace."""
    return int(_match_edge_text(text, r"\d+$"))
