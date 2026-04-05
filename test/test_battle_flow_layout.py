"""战斗流程目录约定与 scope 辅助函数单元测试（直接加载模块文件，避免拉满 AutoScriptor 依赖树）"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MOD_PATH = _REPO / "AutoScriptor" / "utils" / "flow_yaml_layout.py"
_spec = importlib.util.spec_from_file_location("flow_yaml_layout_under_test", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
iter_flow_yaml_files = _mod.iter_flow_yaml_files
flow_yaml_scope_kind = _mod.flow_yaml_scope_kind


class TestFlowLayout(unittest.TestCase):
    def test_iter_order_flat_then_common_then_sub(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "流程"
            root.mkdir(parents=True)
            (root / "a.yaml").write_text("A: {}\n", encoding="utf-8")
            common = root / "通用"
            common.mkdir()
            (common / "b.yaml").write_text("B: {}\n", encoding="utf-8")
            sub = root / "昆仑山"
            sub.mkdir()
            (sub / "c.yaml").write_text("C: {}\n", encoding="utf-8")
            paths = list(iter_flow_yaml_files(root))
            self.assertEqual([p.name for p in paths], ["a.yaml", "b.yaml", "c.yaml"])

    def test_scope_kind_flat_and_common_and_leaf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "流程"
            root.mkdir(parents=True)
            f1 = root / "x.yaml"
            f1.write_text("x: {}\n", encoding="utf-8")
            self.assertEqual(flow_yaml_scope_kind(f1, root), "global")
            common = root / "通用"
            common.mkdir()
            f2 = common / "y.yaml"
            f2.write_text("y: {}\n", encoding="utf-8")
            self.assertEqual(flow_yaml_scope_kind(f2, root), "global")
            sub = root / "昆仑山"
            sub.mkdir()
            f3 = sub / "z.yaml"
            f3.write_text("z: {}\n", encoding="utf-8")
            self.assertEqual(flow_yaml_scope_kind(f3, root), "昆仑山")


if __name__ == "__main__":
    unittest.main()
