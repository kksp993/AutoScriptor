"""账号文档的 dispatch_queue 默认值。

调度器只跑 dispatch_queue 里的角色，所以账号文档必须带这个键；否则新账号
配好任务后点启动调度只会得到「调度队列为空，请先添加要参与调度的角色」。

覆盖三条路径：

1. 全新账号文件（``_default_account_payload`` / ``add_account``）自带队列；
2. 既有账号缺键时在加载期补齐并落盘一次，已补齐的不重复写盘；
3. 用户显式清空（``[]``）视为明确意图，加载期不再自动填回。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("AUTOSCRIPTOR_TESTING", "1")

from ZmxyOL.accounts.account_store import Account, AccountStore


def character_tree() -> dict:
    return {
        "默认服务器": {
            "老王": {"tasks": {}, "status": {}},
            "小李": {"tasks": {}, "status": {}},
        }
    }


class DefaultAccountPayloadTest(unittest.TestCase):
    def test_new_account_file_already_carries_its_character(self):
        payload = AccountStore._default_account_payload("steve")

        self.assertEqual(
            payload["dispatch_queue"],
            [{"server": "默认服务器", "name": "steve"}],
        )


class EnsureDispatchQueueTest(unittest.TestCase):
    """``Account.ensure_dispatch_queue`` 的补齐规则。"""

    def test_missing_key_is_filled_with_the_active_character(self):
        document = {
            "active_character": {"server": "默认服务器", "name": "老王"},
            "characters": character_tree(),
        }

        changed = Account("a", document).ensure_dispatch_queue()

        self.assertTrue(changed)
        self.assertEqual(document["dispatch_queue"], [{"server": "默认服务器", "name": "老王"}])

    def test_an_explicitly_emptied_queue_is_left_alone(self):
        document = {
            "active_character": {"server": "默认服务器", "name": "老王"},
            "characters": character_tree(),
            "dispatch_queue": [],
        }

        changed = Account("a", document).ensure_dispatch_queue()

        self.assertFalse(changed)
        self.assertEqual(document["dispatch_queue"], [])

    def test_existing_queue_is_never_rewritten(self):
        queued = [{"server": "默认服务器", "name": "小李"}]
        document = {
            "active_character": {"server": "默认服务器", "name": "老王"},
            "characters": character_tree(),
            "dispatch_queue": queued,
        }

        self.assertFalse(Account("a", document).ensure_dispatch_queue())
        self.assertEqual(document["dispatch_queue"], queued)

    def test_account_without_characters_keeps_the_key_missing(self):
        """没有角色时写不了队列；保持缺键，等它有角色后下一次加载再补。"""
        document = {"active_character": {"server": "", "name": ""}, "characters": {}}

        self.assertFalse(Account("a", document).ensure_dispatch_queue())
        self.assertNotIn("dispatch_queue", document)

    def test_stale_active_character_falls_back_to_the_first_one(self):
        document = {
            "active_character": {"server": "默认服务器", "name": "已经删掉的角色"},
            "characters": character_tree(),
        }

        changed = Account("a", document).ensure_dispatch_queue()

        self.assertTrue(changed)
        self.assertEqual(document["dispatch_queue"], [{"server": "默认服务器", "name": "老王"}])


class LoadAccountPersistenceTest(unittest.TestCase):
    """加载既有账号文件时，补齐结果只落盘一次。"""

    def _write_account(self, directory: Path, account_name: str, document: dict) -> Path:
        account_path = directory / f"{account_name}.json"
        account_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return account_path

    def _load(self, store: AccountStore, directory: Path, account_name: str, writes: list) -> None:
        def writer(path, data):
            writes.append(str(path))
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        store.load_account(account_name, "", {"accounts": {"dir": str(directory)}}, writer)

    def test_loading_a_legacy_account_fills_and_persists_the_queue_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            account_path = self._write_account(
                directory,
                "legacy",
                {
                    "encryption": {},
                    "active_character": {"server": "默认服务器", "name": "老王"},
                    "characters": {"默认服务器": {"老王": {"tasks": {}, "status": {}}}},
                },
            )
            store = AccountStore()
            writes: list[str] = []

            self._load(store, directory, "legacy", writes)

            self.assertEqual(len(writes), 1)
            saved = json.loads(account_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["dispatch_queue"], [{"server": "默认服务器", "name": "老王"}])
            # 角色任务表不受影响。
            self.assertIn("老王", saved["characters"]["默认服务器"])

            # 已经补齐过的账号再加载一次不重复写盘。
            writes.clear()
            self._load(store, directory, "legacy", writes)
            self.assertEqual(writes, [])

    def test_loading_an_account_that_emptied_its_queue_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            account_path = self._write_account(
                directory,
                "cleared",
                {
                    "encryption": {},
                    "active_character": {"server": "默认服务器", "name": "老王"},
                    "characters": {"默认服务器": {"老王": {"tasks": {}, "status": {}}}},
                    "dispatch_queue": [],
                },
            )
            writes: list[str] = []

            self._load(AccountStore(), directory, "cleared", writes)

            self.assertEqual(writes, [])
            saved = json.loads(account_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["dispatch_queue"], [])


if __name__ == "__main__":
    unittest.main()
