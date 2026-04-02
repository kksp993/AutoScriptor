"""content_update_security URL 与校验逻辑测试（无网络）"""

import base64
import os
import socket
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

from services.core.content_update_security import (  # noqa: E402
    assert_url_safe_for_download,
    manifest_bytes_for_signing,
    validate_manifest_artifact_hashes,
    verify_manifest_ed25519_if_configured,
)


class TestUrlPolicy(unittest.TestCase):
    @patch(
        "services.core.content_update_security.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        ],
    )
    def test_https_resolves_to_public_ip_ok(self, _mock):
        assert_url_safe_for_download("https://example.com/path/x.bin")

    def test_allowlist_skips_dns(self):
        old = os.environ.get("AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS")
        os.environ["AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS"] = "my.cdn.example"
        try:
            assert_url_safe_for_download("https://my.cdn.example/a.bin")
        finally:
            if old is None:
                del os.environ["AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS"]
            else:
                os.environ["AUTOSCRIPTOR_CONTENT_UPDATE_ALLOWED_HOSTS"] = old

    def test_http_blocked_by_default(self):
        with self.assertRaises(ValueError):
            assert_url_safe_for_download("http://example.com/a.bin")

    def test_loopback_ip_blocked(self):
        with self.assertRaises(ValueError):
            assert_url_safe_for_download("https://127.0.0.1/a.bin")


class TestManifestHashes(unittest.TestCase):
    def test_valid_hex(self):
        h = "a" * 64
        validate_manifest_artifact_hashes(
            {
                "content_version": "1",
                "artifacts": [
                    {
                        "kind": "raw",
                        "relative_path": "a.js",
                        "url": "https://example.com/a.js",
                        "sha256": h,
                    }
                ],
            }
        )

    def test_invalid_hex(self):
        with self.assertRaises(ValueError):
            validate_manifest_artifact_hashes(
                {
                    "content_version": "1",
                    "artifacts": [
                        {
                            "kind": "raw",
                            "relative_path": "a.js",
                            "url": "https://example.com/a.js",
                            "sha256": "not-hex",
                        }
                    ],
                }
            )


class TestEd25519Optional(unittest.TestCase):
    def test_no_key_no_sig_ok(self):
        verify_manifest_ed25519_if_configured({"content_version": "1", "artifacts": []})

    def test_signing_payload_stable(self):
        m = {"content_version": "1", "artifacts": [], "signature_ed25519": "x"}
        b1 = manifest_bytes_for_signing(m)
        self.assertNotIn(b"signature", b1)

    def test_ed25519_roundtrip(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        pub_pem = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )
        m = {"content_version": "1", "artifacts": []}
        payload = manifest_bytes_for_signing(m)
        sig = base64.b64encode(key.sign(payload)).decode("ascii")
        m2 = {**m, "signature_ed25519": sig}
        verify_manifest_ed25519_if_configured(m2, public_key_pem=pub_pem)


class TestMinIntervalLimiter(unittest.TestCase):
    def test_blocks_burst(self):
        from services.webui.security import MinIntervalLimiter

        lim = MinIntervalLimiter(min_interval_sec=60.0)
        self.assertTrue(lim.allow("1.1.1.1"))
        self.assertFalse(lim.allow("1.1.1.1"))


if __name__ == "__main__":
    unittest.main()
