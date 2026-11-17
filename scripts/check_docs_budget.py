"""Check the maintained documentation budget without importing the application."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
from typing import Sequence
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOTAL_WORD_LIMIT = 10_000
FILE_WORD_LIMIT = 500
EXCLUDED_ROOT_DIRECTORIES = frozenset({"refs"})
CJK_RANGES = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af"
WORD_PATTERN = re.compile(
    rf"[{CJK_RANGES}]|[^\W_{CJK_RANGES}]+(?:_[^\W_{CJK_RANGES}]+)*",
    flags=re.UNICODE,
)
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
FENCED_CODE_PATTERN = re.compile(r"^\s*```[^\n]*\n.*?^\s*```\s*$", re.MULTILINE | re.DOTALL)


def count_words(content: str) -> int:
    """Count each Han character and each remaining alphanumeric word, including code."""
    return sum(1 for _ in WORD_PATTERN.finditer(content))


def raise_walk_error(error: OSError) -> None:
    raise error


def collect_document_counts(documentation_root: Path) -> list[tuple[Path, int]]:
    """Include hidden files and ignore only the explicitly excluded third-party clones."""
    if not documentation_root.is_dir():
        raise ValueError(f"Documentation directory does not exist: {documentation_root}")

    document_counts = []
    for directory, child_directories, filenames in os.walk(documentation_root, onerror=raise_walk_error):
        directory_path = Path(directory)
        if directory_path == documentation_root:
            child_directories[:] = [
                name for name in child_directories if name not in EXCLUDED_ROOT_DIRECTORIES
            ]
        for filename in sorted(filenames):
            document_path = directory_path / filename
            # Fail on unreadable or non-UTF-8 documents rather than silently undercounting.
            content = document_path.read_text(encoding="utf-8-sig")
            document_counts.append((document_path.relative_to(documentation_root), count_words(content)))
    return sorted(document_counts)


def collect_broken_links(
    documentation_root: Path, document_paths: Sequence[Path],
) -> list[str]:
    """Check local Markdown link destinations; external URLs and fragments are not fetched."""
    broken_links = []
    for relative_path in document_paths:
        document_path = documentation_root / relative_path
        content = FENCED_CODE_PATTERN.sub(
            lambda match: "\n" * match.group(0).count("\n"),
            document_path.read_text(encoding="utf-8-sig"),
        )
        for match in MARKDOWN_LINK_PATTERN.finditer(content):
            destination_parts = match.group(1).strip().split(maxsplit=1)
            if not destination_parts:
                continue
            destination = destination_parts[0].strip("<>")
            parsed_destination = urlsplit(destination)
            if parsed_destination.scheme or parsed_destination.netloc or not parsed_destination.path:
                continue
            target_path = document_path.parent / unquote(parsed_destination.path)
            if not target_path.exists():
                line_number = content.count("\n", 0, match.start()) + 1
                broken_links.append(f"{relative_path.as_posix()}:{line_number}: {destination}")
    return broken_links


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "docs")
    parser.add_argument("--details", action="store_true", help="Print every document's word count")
    options = parser.parse_args(arguments)

    try:
        document_counts = collect_document_counts(options.root.resolve())
        broken_links = collect_broken_links(
            options.root.resolve(), [document_path for document_path, _ in document_counts],
        )
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"Documentation scan failed: {error}\n")

    total_words = sum(word_count for _, word_count in document_counts)
    oversized_documents = [
        (document_path, word_count)
        for document_path, word_count in document_counts
        if word_count > FILE_WORD_LIMIT
    ]
    for document_path, word_count in document_counts:
        if options.details or word_count > FILE_WORD_LIMIT:
            print(f"{word_count:6d}  {document_path.as_posix()}")
    largest_document = max(document_counts, key=lambda item: item[1], default=(Path("."), 0))
    print(f"Documents: {len(document_counts)}; words: {total_words}/{TOTAL_WORD_LIMIT}")
    print(f"Largest: {largest_document[0].as_posix()} ({largest_document[1]}/{FILE_WORD_LIMIT})")
    print("Scope: all files under docs/, excluding docs/refs/ third-party clones.")
    for broken_link in broken_links:
        print(f"Broken link: {broken_link}")
    print(f"Local link destinations: {len(broken_links)} broken; fragments/external URLs not checked.")
    passed = total_words <= TOTAL_WORD_LIMIT and not oversized_documents and not broken_links
    print("PASS" if passed else f"FAIL: {len(oversized_documents)} oversized documents, {len(broken_links)} broken links")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
