"""One-click setup for QQ notifications.

Takes a machine that has nothing but this project and leaves it sending task
results to a QQ friend or group. The only step that cannot be automated is the
first QQ login: Tencent requires a QR scan on a new device even when a password
is supplied, so the browser is opened at the panel that shows it. Every later
start is a quick login with no interaction.

Interactive by default; ``--qq`` / ``--to`` / ``--yes`` make it scriptable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time
import webbrowser


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core import onebot  # noqa: E402
from backend.core import qq_bot  # noqa: E402


STEP = 0


def step(title: str) -> None:
    global STEP
    STEP += 1
    print(f"\n[{STEP}] {title}", flush=True)


def ask(prompt: str, default: str = "") -> str:
    """Ask one question. An empty answer takes the default."""
    suffix = f"（默认 {default}）" if default else ""
    try:
        answer = input(f"    {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("已取消。") from None
    return answer or default


def auto_yes(flags: argparse.Namespace) -> bool:
    return bool(flags.yes) or not sys.stdin.isatty()


def pick(prompt: str, options: list[str], flags: argparse.Namespace) -> str:
    """Choose one of ``options``, defaulting to the first."""
    if len(options) == 1:
        print(f"    {prompt}: {options[0]}")
        return options[0]
    for index, option in enumerate(options, 1):
        print(f"      {index}) {option}")
    if auto_yes(flags):
        print(f"    {prompt}: {options[0]}")
        return options[0]
    answer = ask(prompt, "1")
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1]
    return answer


def config_path() -> Path:
    from AutoScriptor.utils.paths import get_config_path

    return Path(get_config_path())


def autoscriptor_is_running() -> bool:
    """Whether the WebUI owns data/config.json right now."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", 5000)) == 0


def write_notify_settings(endpoint: str, token: str, target_type: str, target_id: str) -> Path:
    """Write only the ``notify.qq`` block, atomically, leaving the rest alone."""
    # Imported from json_io rather than app_config: app_config builds the cfg
    # singleton at import time and saves it again on exit, which would write the
    # pre-edit snapshot back over this change.
    from AutoScriptor.utils.json_io import write_json_atomic

    path = config_path()
    document: dict = {}
    if path.is_file():
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    notify = document.setdefault("notify", {})
    if not isinstance(notify, dict):
        notify = document["notify"] = {}
    qq = notify.setdefault("qq", {})
    if not isinstance(qq, dict):
        qq = notify["qq"] = {}
    qq.update({
        "enabled": True,
        "endpoint": endpoint,
        "target_type": target_type,
        "target_id": str(target_id),
        "access_token": token,
    })
    write_json_atomic(path, document)
    return path


def wait_for_login(
    endpoint: str,
    token: str,
    *,
    timeout: float,
    label: str,
) -> dict | None:
    """Poll until the bot reports a logged-in account."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        account = onebot.probe_login(endpoint, token, timeout=3.0)
        if account:
            print(f"\r    {label}完成：{account.get('nickname')} ({account.get('user_id')})", flush=True)
            return account
        print("\r    等待登录…", end="", flush=True)
        time.sleep(2)
    print()
    return None


def bot_is_serving(endpoint: str, token: str) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", int(endpoint.rsplit(":", 1)[-1]))) != 0:
            return False
    return onebot.probe_login(endpoint, token, timeout=3.0) is not None


def run(flags: argparse.Namespace) -> int:
    print("AutoScriptor QQ 通知 一键设置")
    print("  机器人用一个 QQ 小号登录；通知发给你的主号。第三方 QQ 自动化有风控风险，请用小号。")

    # ── 0. 位置 ──
    step("检查存放位置")
    qq_bot.assert_private_location()
    print(f"    机器人目录：{qq_bot.BOT_ROOT}")

    # ── 1. 安装 ──
    step("准备 NapCat")
    if qq_bot.load_local_settings() is None:
        print("    未安装，开始下载（约 110 MB，只需一次）…")
        qq_bot.install_bot()
    else:
        print("    已安装，保留现有令牌与登录数据。")
    settings = qq_bot.load_local_settings()
    endpoint = f"http://127.0.0.1:{settings['http_port']}"
    token = settings["access_token"]

    # ── 2. 登录 ──
    step("登录机器人 QQ")
    account: dict | None = None
    if bot_is_serving(endpoint, token):
        account = onebot.probe_login(endpoint, token)
        print(f"    机器人已在运行：{account.get('nickname')} ({account.get('user_id')})")
    else:
        cached = qq_bot.cached_accounts()
        remembered = qq_bot.remembered_account()
        chosen = ""
        if flags.qq:
            # Explicit on the command line: trust it, but only quick-login when
            # a session for it exists, otherwise the bot would wait forever.
            chosen = flags.qq.strip() if flags.qq.strip() in cached else ""
            if not chosen:
                print(f"    {flags.qq} 在这台机器上没有会话，需要扫码一次。")
        elif cached:
            if remembered in cached:
                cached = [remembered] + [q for q in cached if q != remembered]
            chosen = pick("选择要登录的 QQ", cached, flags)

        print(f"    启动机器人{f'（快速登录 {chosen}）' if chosen else ''}…")
        qq_bot.launch_bot(account=chosen)
        account = wait_for_login(endpoint, token, timeout=25 if chosen else 3, label="快速登录")

        if account is None and not chosen:
            # No cached session: Tencent requires a scan on a new device.
            url = qq_bot.webui_login_url()
            print("    这台机器还没登录过这个 QQ，需要扫码一次（以后不再需要）。")
            print(f"    已打开登录页面：{url}")
            if not flags.no_browser:
                webbrowser.open(url)
            else:
                print("    请手动打开上面的地址。")
            account = wait_for_login(endpoint, token, timeout=240, label="扫码登录")

        if account is None:
            print("    登录没有完成。可以在浏览器里打开上面的地址重试，或重新运行本脚本。")
            return 1

    # ── 3. 记住这个号 ──
    number = str(account.get("user_id") or "")
    qq_bot.remember_account(number)

    # ── 4. 接收人 ──
    step("选择接收通知的 QQ")
    recipients = onebot.list_recipients(endpoint, token)
    if not recipients:
        print("    这个机器人账号还没有任何好友或群。")
        print("    请先用它加你的主号为好友（或拉进一个群），然后重新运行本脚本。")
        return 1
    labels = [f"{r['name']}（{'好友' if r['type'] == 'private' else '群'} {r['id']}）" for r in recipients]
    if flags.to:
        wanted = str(flags.to).strip()
        target = next((r for r in recipients if r["id"] == wanted), None)
        if target is None:
            print(f"    {wanted} 不在这个机器人的好友或群列表里，改为手动选择。")
    if not flags.to or target is None:
        choice = pick("通知发给", labels, flags)
        target = recipients[labels.index(choice)] if choice in labels else recipients[0]

    # ── 5. 写入 AutoScriptor ──
    step("写入 AutoScriptor 配置")
    path = write_notify_settings(endpoint, token, target["type"], target["id"])
    print(f"    已写入 {path}")
    print(f"    机器人：{account.get('nickname')} ({number})")
    print(f"    接收人：{target['name']} ({target['id']})")
    if autoscriptor_is_running():
        print("    AutoScriptor 正在运行，重新加载任务后生效（无需重启机器人）。")

    # ── 6. 测试 ──
    step("发送测试消息")
    message_id = onebot.deliver(
        endpoint, token, target["type"], target["id"],
        "AutoScriptor 通知已连接。\n"
        "这条是设置脚本发出的测试消息；之后任务执行结果会发到这里。",
    )
    print(f"    已发送（message_id {message_id}），请到 QQ 确认收到。")

    print("\n完成。以后这样用：")
    print("    启动机器人：scripts\\qq-notify\\2-start.cmd    （快速登录，无需扫码）")
    print("    停止机器人：scripts\\qq-notify\\3-stop.cmd")
    print("    机器人常开即可，不影响模拟器与任务执行。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qq", help="要登录的机器人 QQ 号（已有会话时可直接指定）")
    parser.add_argument("--to", help="接收通知的 QQ 号或群号")
    parser.add_argument("--yes", action="store_true", help="全部使用默认值，不提问")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开扫码页面")
    flags = parser.parse_args()
    try:
        return run(flags)
    except (OSError, ValueError, onebot.OneBotError) as error:
        print(f"\n失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
