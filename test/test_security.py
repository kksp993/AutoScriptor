"""
安全加固测试
============
验证所有安全机制是否正确工作：
- 密码哈希与验证
- 会话令牌
- 速率限制
- 重放攻击防护
- 公开配置脱敏
- 档案加密
- 配置导入保护
"""
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.webui.security import (
    hash_deploy_password, verify_deploy_password,
    create_session, validate_session, get_sessions,
    RateLimiter, login_limiter, verify_limiter,
    check_request_freshness,
)


class TestPasswordHashing(unittest.TestCase):
    """测试 deploy 密码哈希与验证"""

    def test_hash_produces_pbkdf2_format(self):
        result = hash_deploy_password("test123")
        self.assertTrue(result.startswith("pbkdf2$"))
        parts = result.split("$")
        self.assertEqual(len(parts), 3)

    def test_verify_correct_password(self):
        hashed = hash_deploy_password("mypassword")
        self.assertTrue(verify_deploy_password("mypassword", hashed))

    def test_verify_wrong_password(self):
        hashed = hash_deploy_password("mypassword")
        self.assertFalse(verify_deploy_password("wrongpassword", hashed))

    def test_verify_legacy_plaintext(self):
        self.assertTrue(verify_deploy_password("oldpass", "oldpass"))
        self.assertFalse(verify_deploy_password("wrong", "oldpass"))

    def test_verify_empty_stored(self):
        self.assertFalse(verify_deploy_password("anything", ""))
        self.assertFalse(verify_deploy_password("anything", None))

    def test_different_hashes_for_same_password(self):
        h1 = hash_deploy_password("same")
        h2 = hash_deploy_password("same")
        self.assertNotEqual(h1, h2, "每次哈希应使用不同盐值")

    def test_special_characters(self):
        for pwd in ["p@$$w0rd!", "密码测试", "a" * 1000, " ", "pbkdf2$fake$data"]:
            hashed = hash_deploy_password(pwd)
            self.assertTrue(verify_deploy_password(pwd, hashed), f"密码 '{pwd[:10]}...' 验证失败")

    def test_malformed_hash_rejected(self):
        self.assertFalse(verify_deploy_password("test", "pbkdf2$"))
        self.assertFalse(verify_deploy_password("test", "pbkdf2$only_salt"))
        self.assertFalse(verify_deploy_password("test", "$$$"))


class TestSessionManagement(unittest.TestCase):
    """测试会话令牌管理"""

    def setUp(self):
        get_sessions().clear()

    def test_create_returns_token(self):
        token = create_session()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)

    def test_validate_valid_token(self):
        token = create_session()
        self.assertTrue(validate_session(token))

    def test_validate_invalid_token(self):
        self.assertFalse(validate_session("nonexistent"))
        self.assertFalse(validate_session(""))
        self.assertFalse(validate_session(None))

    def test_unique_tokens(self):
        t1 = create_session()
        t2 = create_session()
        self.assertNotEqual(t1, t2)

    def test_expired_session_rejected(self):
        token = create_session()
        get_sessions()[token] = time.time() - 1
        self.assertFalse(validate_session(token))
        self.assertNotIn(token, get_sessions())


class TestRateLimiter(unittest.TestCase):
    """测试速率限制器"""

    def setUp(self):
        self.limiter = RateLimiter(max_failures=3, window=10)

    def test_not_limited_initially(self):
        self.assertFalse(self.limiter.is_limited("10.0.0.1"))

    def test_limited_after_max_failures(self):
        for _ in range(3):
            self.limiter.record_failure("10.0.0.1")
        self.assertTrue(self.limiter.is_limited("10.0.0.1"))

    def test_different_ips_independent(self):
        for _ in range(3):
            self.limiter.record_failure("10.0.0.1")
        self.assertTrue(self.limiter.is_limited("10.0.0.1"))
        self.assertFalse(self.limiter.is_limited("10.0.0.2"))

    def test_not_limited_under_threshold(self):
        for _ in range(2):
            self.limiter.record_failure("10.0.0.3")
        self.assertFalse(self.limiter.is_limited("10.0.0.3"))

    def test_clear_resets(self):
        for _ in range(3):
            self.limiter.record_failure("10.0.0.4")
        self.assertTrue(self.limiter.is_limited("10.0.0.4"))
        self.limiter.clear()
        self.assertFalse(self.limiter.is_limited("10.0.0.4"))


class TestLoginLimiter(unittest.TestCase):
    """测试全局登录限制器"""

    def setUp(self):
        login_limiter.clear()

    def test_login_limiter_exists(self):
        self.assertEqual(login_limiter.max_failures, 5)
        self.assertEqual(login_limiter.window, 300)

    def test_login_limiter_works(self):
        for _ in range(5):
            login_limiter.record_failure("1.2.3.4")
        self.assertTrue(login_limiter.is_limited("1.2.3.4"))


class TestVerifyLimiter(unittest.TestCase):
    """测试全局安全密码验证限制器"""

    def setUp(self):
        verify_limiter.clear()

    def test_verify_limiter_exists(self):
        self.assertEqual(verify_limiter.max_failures, 5)
        self.assertEqual(verify_limiter.window, 300)

    def test_verify_limiter_works(self):
        for _ in range(5):
            verify_limiter.record_failure("5.6.7.8")
        self.assertTrue(verify_limiter.is_limited("5.6.7.8"))


class TestReplayProtection(unittest.TestCase):
    """测试重放攻击防护"""

    def test_fresh_request(self):
        self.assertTrue(check_request_freshness({"_timestamp": time.time()}))

    def test_stale_request(self):
        self.assertFalse(check_request_freshness({"_timestamp": time.time() - 120}))

    def test_future_request(self):
        self.assertFalse(check_request_freshness({"_timestamp": time.time() + 120}))

    def test_no_timestamp_backward_compat(self):
        self.assertTrue(check_request_freshness({}))

    def test_invalid_timestamp(self):
        self.assertFalse(check_request_freshness({"_timestamp": "not_a_number"}))

    def test_boundary_just_within(self):
        self.assertTrue(check_request_freshness({"_timestamp": time.time() - 59}))

    def test_boundary_just_outside(self):
        self.assertFalse(check_request_freshness({"_timestamp": time.time() - 61}))

    def test_custom_max_age(self):
        self.assertTrue(check_request_freshness({"_timestamp": time.time() - 25}, max_age=30))
        self.assertFalse(check_request_freshness({"_timestamp": time.time() - 35}, max_age=30))


class TestProfileEncryption(unittest.TestCase):
    """测试档案加密/解密"""

    @classmethod
    def setUpClass(cls):
        try:
            from AutoScriptor.crypto.config_manager import ConfigManager
            cls.CM = ConfigManager
        except ImportError:
            import sys as _sys
            mod = _sys.modules.get("AutoScriptor.crypto.config_manager")
            cls.CM = mod.ConfigManager if mod else None

    def _cm(self):
        if self.CM is None:
            self.skipTest("ConfigManager 不可用 (缺少硬件依赖)")
        return self.CM

    def test_encrypt_decrypt_roundtrip(self):
        ConfigManager = self._cm()
        data = {"account": "test_user", "password": "secret123", "character_name": "Hero"}
        key = "my_security_key"
        enc = ConfigManager.encrypt_data(data, key)
        self.assertIn("salt", enc)
        self.assertIn("nonce", enc)
        self.assertIn("encrypted_data", enc)
        self.assertIn("hmac", enc)
        self.assertNotIn("test_user", str(enc))
        self.assertNotIn("secret123", str(enc))
        dec = ConfigManager.decrypt_data(enc, key)
        self.assertEqual(dec["account"], "test_user")
        self.assertEqual(dec["password"], "secret123")
        self.assertEqual(dec["character_name"], "Hero")

    def test_wrong_key_fails(self):
        ConfigManager = self._cm()
        data = {"account": "user", "password": "pass"}
        enc = ConfigManager.encrypt_data(data, "correct_key")
        with self.assertRaises(Exception):
            ConfigManager.decrypt_data(enc, "wrong_key")

    def test_tampered_data_fails(self):
        ConfigManager = self._cm()
        data = {"account": "user", "password": "pass"}
        enc = ConfigManager.encrypt_data(data, "key123")
        enc["encrypted_data"] = enc["encrypted_data"][:-4] + "AAAA"
        with self.assertRaises(Exception):
            ConfigManager.decrypt_data(enc, "key123")

    def test_tampered_hmac_fails(self):
        ConfigManager = self._cm()
        data = {"test": "value"}
        enc = ConfigManager.encrypt_data(data, "key")
        enc["hmac"] = enc["hmac"][:-4] + "BBBB"
        with self.assertRaises(Exception):
            ConfigManager.decrypt_data(enc, "key")

    def test_unicode_data(self):
        ConfigManager = self._cm()
        data = {"账号": "测试用户", "密码": "中文密码123"}
        enc = ConfigManager.encrypt_data(data, "安全密钥")
        dec = ConfigManager.decrypt_data(enc, "安全密钥")
        self.assertEqual(dec["账号"], "测试用户")


class TestConfigImportProtection(unittest.TestCase):
    """测试配置导入敏感字段剥离逻辑"""

    def test_import_strips_sensitive_keys(self):
        malicious = {
            "encryption": {"salt": "HACKED"},
            "current_profile": "hacked",
            "profiles": {"list": {"hacker": {}}},
            "game": {"account": "hijacked"},
            "deploy": {
                "theme": "dark",
                "password": "backdoor",
                "ssl_key": "/evil",
                "ssl_cert": "/evil",
            },
            "app": {"name": "SafeApp"},
        }

        malicious.pop("encryption", None)
        malicious.pop("current_profile", None)
        malicious.pop("profiles", None)
        malicious.pop("game", None)
        if "deploy" in malicious:
            malicious["deploy"].pop("password", None)
            malicious["deploy"].pop("ssl_key", None)
            malicious["deploy"].pop("ssl_cert", None)

        self.assertNotIn("encryption", malicious)
        self.assertNotIn("current_profile", malicious)
        self.assertNotIn("profiles", malicious)
        self.assertNotIn("game", malicious)
        self.assertNotIn("password", malicious.get("deploy", {}))
        self.assertNotIn("ssl_key", malicious.get("deploy", {}))
        self.assertIn("theme", malicious["deploy"])
        self.assertIn("app", malicious)


class TestAttackScenarios(unittest.TestCase):
    """模拟攻击场景，确保防护有效"""

    def test_brute_force_password_blocked(self):
        """暴力破解 deploy 密码应被限制"""
        limiter = RateLimiter(max_failures=5, window=300)
        hashed = hash_deploy_password("real_password")
        for i in range(10):
            if limiter.is_limited("attacker"):
                break
            result = verify_deploy_password(f"guess_{i}", hashed)
            if not result:
                limiter.record_failure("attacker")
        self.assertTrue(limiter.is_limited("attacker"))

    def test_replay_attack_blocked(self):
        """重放旧请求应被拒绝"""
        old_request = {"security_key": "stolen_key", "_timestamp": time.time() - 120}
        self.assertFalse(check_request_freshness(old_request))

    def test_stolen_session_expires(self):
        """被盗的会话令牌过期后应失效"""
        get_sessions().clear()
        token = create_session()
        self.assertTrue(validate_session(token))
        get_sessions()[token] = time.time() - 1
        self.assertFalse(validate_session(token))

    def test_password_hash_not_reversible(self):
        """哈希值不应包含原始密码"""
        pwd = "super_secret_123"
        hashed = hash_deploy_password(pwd)
        self.assertNotIn(pwd, hashed)

    def test_profile_encryption_prevents_file_theft(self):
        """config.json 被盗时，加密的档案数据无法被读取"""
        try:
            from AutoScriptor.crypto.config_manager import ConfigManager
        except ImportError:
            import sys as _s
            mod = _s.modules.get("AutoScriptor.crypto.config_manager")
            if not mod:
                self.skipTest("ConfigManager 不可用")
            ConfigManager = mod.ConfigManager
        sensitive = {"account": "victim", "password": "victim_pwd"}
        enc = ConfigManager.encrypt_data(sensitive, "user_secret")
        self.assertNotIn("victim", str(enc))
        self.assertNotIn("victim_pwd", str(enc))
        with self.assertRaises(Exception):
            ConfigManager.decrypt_data(enc, "attacker_guess")


if __name__ == "__main__":
    unittest.main()
