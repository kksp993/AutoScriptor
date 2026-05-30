import unittest

from AutoScriptor.vlm.skills import load_agent_skills
from AutoScriptor.vlm.vlm import _infer_api_format, _openai_base, _strip_thinking


class VLMClientCompatTest(unittest.TestCase):
    def test_openai_base_normalization(self):
        self.assertEqual(_openai_base("https://vlm.example.invalid/v1"), "https://vlm.example.invalid/v1")
        self.assertEqual(
            _openai_base("https://vlm.example.invalid/v1/chat/completions"),
            "https://vlm.example.invalid/v1",
        )
        self.assertEqual(_openai_base("https://vlm.example.invalid"), "https://vlm.example.invalid/v1")

    def test_api_format_inference(self):
        self.assertEqual(_infer_api_format("http://localhost:11434/v1", "auto"), "ollama")
        self.assertEqual(_infer_api_format("https://vlm.example.invalid/v1", "auto"), "openai")
        self.assertEqual(_infer_api_format("http://x/v1", "vllm"), "openai")

    def test_strip_qwen_thinking_tags(self):
        self.assertEqual(_strip_thinking("<think>hidden</think>(123,456)"), "(123,456)")
        self.assertEqual(_strip_thinking("answer</think>"), "answer")

    def test_agent_skills_load(self):
        text = load_agent_skills(["autoscriptor_api", "safe_task_execution"])
        self.assertIn("AutoScriptor API", text)
        self.assertIn("安全执行规则", text)

    def test_default_agent_skills_are_generic_script_guidance(self):
        text = load_agent_skills(None)
        self.assertIn("短流程脚本", text)
        self.assertIn("最终脚本不能包含 `V(...)`", text)
        self.assertIn("click((T(...), I(...)))", text)
        self.assertIn("购物/消耗先确认可买", text)
        self.assertIn("BattleFlowName", text)
        self.assertIn("不能留下占位符", text)
        self.assertIn("不要生成 `if __name__ == \"__main__\"`", text)
        self.assertNotIn("兑换豪礼", text)
        self.assertNotIn("礼品兑换", text)

    def test_vlm_docs_and_tests_do_not_expose_local_deployment(self):
        from pathlib import Path

        roots = [
            Path("AutoScriptor/vlm"),
            Path("docs/AutoScriptor/refactor"),
            Path("test/test_vlm_client_compat.py"),
        ]
        forbidden = ("sdu" + "-112", "Qwen" + "3.6", "211" + ".87")
        for root in roots:
            files = [root] if root.is_file() else list(root.rglob("*"))
            for path in files:
                if path.suffix not in {".py", ".md", ".json"}:
                    continue
                text = path.read_text(encoding="utf-8")
                for needle in forbidden:
                    self.assertNotIn(needle, text, str(path))


if __name__ == "__main__":
    unittest.main()
