"""bsdiff 增量与清单应用逻辑单元测试"""

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

from services.core.binary_delta import (  # noqa: E402
    apply_bsdiff_patch,
    create_bsdiff_patch,
    resolve_safe_path,
    sha256_file,
)


class TestBinaryDeltaRoundTrip(unittest.TestCase):
    def test_diff_patch_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            old_p = os.path.join(d, "old.bin")
            new_p = os.path.join(d, "new.bin")
            patch_p = os.path.join(d, "p.bsdiff")
            out_p = os.path.join(d, "out.bin")
            # 模拟「大文件」：大量零 + 少量改动
            old_data = b"\x00" * 50000 + b"ORIGINAL_TAIL"
            new_data = b"\x00" * 50000 + b"MODIFIED_TAIL!!"
            with open(old_p, "wb") as f:
                f.write(old_data)
            with open(new_p, "wb") as f:
                f.write(new_data)

            meta = create_bsdiff_patch(old_p, new_p, patch_p)
            self.assertIn("patch_sha256", meta)
            self.assertLess(os.path.getsize(patch_p), len(old_data))

            apply_bsdiff_patch(
                old_p,
                patch_p,
                out_p,
                expected_new_sha256=meta["new_sha256"],
            )
            with open(out_p, "rb") as f:
                self.assertEqual(f.read(), new_data)
            self.assertEqual(sha256_file(out_p), meta["new_sha256"])


class TestResolveSafePath(unittest.TestCase):
    def test_rejects_parent_segments(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                resolve_safe_path(d, "..\\evil.txt")

    def test_normal_relative(self):
        with tempfile.TemporaryDirectory() as d:
            p = resolve_safe_path(d, "backend/engine.exe")
            self.assertTrue(p.startswith(os.path.abspath(d)))
            self.assertTrue(p.endswith("engine.exe"))


if __name__ == "__main__":
    unittest.main()
