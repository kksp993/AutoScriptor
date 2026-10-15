"""Start the QQ robot in the background. No arguments, no questions.

Separate from ``setup.py`` because this is the everyday action: the account is
already remembered, so it is a quick login and the caller should not be asked
anything.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core import onebot  # noqa: E402
from backend.core import qq_bot  # noqa: E402


def main() -> int:
    settings = qq_bot.load_local_settings()
    if settings is None:
        print("尚未安装。先运行 scripts\\qq-notify\\1-setup.cmd")
        return 1

    endpoint = f"http://127.0.0.1:{settings['http_port']}"
    token = settings["access_token"]
    if onebot.probe_login(endpoint, token):
        account = onebot.probe_login(endpoint, token)
        print(f"已经在运行：{account.get('nickname')} ({account.get('user_id')})")
        return 0

    account_number = qq_bot.remembered_account() or next(iter(qq_bot.cached_accounts()), "")
    qq_bot.launch_bot(account=account_number)

    deadline = time.time() + 30
    while time.time() < deadline:
        account = onebot.probe_login(endpoint, token, timeout=3.0)
        if account:
            print(f"已启动：{account.get('nickname')} ({account.get('user_id')})")
            print("机器人正在后台运行，可以关闭这个窗口。")
            return 0
        time.sleep(2)

    print("启动超时。运行 scripts\\qq-notify\\1-setup.cmd 重新检查登录状态。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
