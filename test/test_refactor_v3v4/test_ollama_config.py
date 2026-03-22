"""
Ollama 配置与部署脚本测试
=========================
覆盖：config template.json llm 字段完整性、vlm/config.py 配置映射、
      setup_ollama.py 脚本可导入性、VLM_CONFIG 字段正确性。
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


class TestConfigTemplate(unittest.TestCase):
    """config template.json 的 llm 部分"""

    @classmethod
    def setUpClass(cls):
        tpl_path = os.path.join(REPO_ROOT, "config template.json")
        with open(tpl_path, "r", encoding="utf-8") as f:
            cls.config = json.load(f)

    def test_llm_section_exists(self):
        self.assertIn("llm", self.config)

    def test_llm_has_use_agent(self):
        self.assertIn("use_agent", self.config["llm"])
        self.assertIsInstance(self.config["llm"]["use_agent"], bool)

    def test_llm_has_url(self):
        url = self.config["llm"]["url"]
        self.assertIn("localhost", url)
        self.assertIn("11434", url)
        self.assertTrue(url.endswith("/v1"))

    def test_llm_has_model(self):
        model = self.config["llm"]["model"]
        self.assertIsInstance(model, str)
        self.assertGreater(len(model), 0)

    def test_llm_default_off(self):
        self.assertFalse(self.config["llm"]["use_agent"])


class TestVLMConfig(unittest.TestCase):
    """AutoScriptor/vlm/config.py 的 VLM_CONFIG"""

    def test_import_vlm_config(self):
        from AutoScriptor.vlm.config import VLM_CONFIG
        self.assertIsInstance(VLM_CONFIG, dict)

    def test_vlm_config_keys(self):
        from AutoScriptor.vlm.config import VLM_CONFIG
        required = {"api_url", "model_name", "max_tokens", "temperature", "timeout"}
        self.assertTrue(required.issubset(set(VLM_CONFIG.keys())))

    def test_vlm_config_model_name_not_slash_model(self):
        from AutoScriptor.vlm.config import VLM_CONFIG
        self.assertNotEqual(VLM_CONFIG["model_name"], "/model")

    def test_vlm_config_api_url_format(self):
        from AutoScriptor.vlm.config import VLM_CONFIG
        url = VLM_CONFIG["api_url"]
        self.assertIsInstance(url, str)
        self.assertTrue(url.startswith("http"), f"api_url should start with http: {url}")


class TestSetupOllamaScript(unittest.TestCase):
    """tools/setup_ollama.py 的可导入性与函数签名"""

    def test_script_importable(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
        try:
            import setup_ollama
            self.assertTrue(hasattr(setup_ollama, "check_ollama_running"))
            self.assertTrue(hasattr(setup_ollama, "check_model_available"))
            self.assertTrue(hasattr(setup_ollama, "pull_model"))
            self.assertTrue(hasattr(setup_ollama, "check_openai_endpoint"))
        finally:
            sys.path.pop(0)

    def test_default_model_matches_config(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
        try:
            import setup_ollama
            tpl_path = os.path.join(REPO_ROOT, "config template.json")
            with open(tpl_path, "r", encoding="utf-8") as f:
                cfg_model = json.load(f)["llm"]["model"]
            self.assertEqual(setup_ollama.DEFAULT_MODEL, cfg_model)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
