"""Enforce the agreed documentation scope and word limits without app/device imports."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_docs_budget import (
    FILE_WORD_LIMIT,
    PROJECT_ROOT,
    TOTAL_WORD_LIMIT,
    collect_broken_links,
    collect_document_counts,
    count_words,
    main,
)


class DocumentationBudgetTest(unittest.TestCase):
    def test_chinese_english_and_code_have_explicit_counts(self):
        self.assertEqual(count_words("\u4e2d\u6587 hello_world 123 \U00020000"), 5)
        self.assertEqual(count_words("\u4e2d\u6587"), count_words("\u4e2d \u6587"))
        self.assertEqual(count_words("```python\nclick(B(1, 2, 3, 4))\n```"), 7)

    def test_only_root_reference_clones_are_excluded(self):
        with TemporaryDirectory() as temporary_directory:
            documentation_root = Path(temporary_directory)
            (documentation_root / "refs").mkdir()
            (documentation_root / "refs" / "upstream.md").write_bytes(b"\xff")
            (documentation_root / ".cursorrules").write_text("visible rule", encoding="utf-8")
            (documentation_root / "guide").mkdir()
            (documentation_root / "guide" / "refs").mkdir()
            (documentation_root / "guide" / "refs" / "owned.md").write_text("owned", encoding="utf-8")
            self.assertEqual(
                collect_document_counts(documentation_root),
                [(Path(".cursorrules"), 2), (Path("guide/refs/owned.md"), 1)],
            )

    def test_unreadable_document_does_not_silently_pass(self):
        with TemporaryDirectory() as temporary_directory:
            documentation_root = Path(temporary_directory)
            (documentation_root / "invalid.md").write_bytes(b"\xff")
            with self.assertRaises(UnicodeError):
                collect_document_counts(documentation_root)

    def test_local_links_are_checked_without_fetching_external_urls(self):
        with TemporaryDirectory() as temporary_directory:
            documentation_root = Path(temporary_directory)
            (documentation_root / "valid target.md").write_text("# Target", encoding="utf-8")
            (documentation_root / "guide.md").write_text(
                "[valid](valid%20target.md#heading)\n"
                "[external](https://example.invalid)\n"
                "```markdown\n[example](not-real.md)\n```\n"
                "[broken](missing.md)\n",
                encoding="utf-8",
            )
            self.assertEqual(
                collect_broken_links(documentation_root, [Path("guide.md")]),
                ["guide.md:6: missing.md"],
            )

    def test_command_rejects_a_file_above_the_limit(self):
        with TemporaryDirectory() as temporary_directory:
            documentation_root = Path(temporary_directory)
            (documentation_root / "long.md").write_text("word " * (FILE_WORD_LIMIT + 1), encoding="utf-8")
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["--root", str(documentation_root)]), 1)

    def test_repository_documentation_stays_within_budget_and_links_resolve(self):
        documentation_root = PROJECT_ROOT / "docs"
        document_counts = collect_document_counts(documentation_root)
        self.assertLessEqual(sum(word_count for _, word_count in document_counts), TOTAL_WORD_LIMIT)
        for document_path, word_count in document_counts:
            with self.subTest(document=document_path.as_posix()):
                self.assertLessEqual(word_count, FILE_WORD_LIMIT)
        self.assertEqual(
            collect_broken_links(documentation_root, [document_path for document_path, _ in document_counts]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
