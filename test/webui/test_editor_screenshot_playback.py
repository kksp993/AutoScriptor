"""Offline editor playback, pause/import cleanup and post-execution screenshots."""

import shutil
import subprocess
import unittest
from pathlib import Path


class EditorScreenshotPlaybackTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for editor interaction checks")
    def test_screenshot_playback_and_execution_completion(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("editor_screenshot_playback.cjs"))],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Editor screenshot playback and execution completion: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
