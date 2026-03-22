"""
防止 Windows 系统锁屏/休眠脚本
功能：
  1. 调用 SetThreadExecutionState 阻止系统自动休眠和关闭显示器
  2. 每隔一段时间模拟鼠标微移，防止系统判定为空闲
  3. 通过注册表禁用 Win+L 锁屏快捷键（退出时自动恢复）
使用方式：以管理员身份运行 python keep_awake.py
退出方式：Ctrl+C（自动恢复所有设置）
"""

import ctypes
import time
import sys
import winreg

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

MOUSE_MOVE = 0x0001

REG_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
REG_NAME = "DisableLockWorkstation"


def set_execution_state():
    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    )


def reset_execution_state():
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def simulate_mouse_move():
    ctypes.windll.user32.mouse_event(MOUSE_MOVE, 1, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(MOUSE_MOVE, -1, 0, 0, 0)


def disable_lock_screen():
    """写入注册表禁用 Win+L 锁屏"""
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        print("[keep_awake] Win+L 锁屏快捷键已禁用")
    except PermissionError:
        print("[keep_awake] 警告：无权限修改注册表，请以管理员身份运行")


def enable_lock_screen():
    """恢复注册表，重新启用 Win+L 锁屏"""
    try:
        key = winreg.OpenKeyEx(
            winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        print("[keep_awake] Win+L 锁屏快捷键已恢复")
    except FileNotFoundError:
        pass


def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(f"[keep_awake] 已启动，每 {interval} 秒刷新一次，Ctrl+C 退出")

    set_execution_state()
    disable_lock_screen()

    try:
        while True:
            set_execution_state()
            simulate_mouse_move()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[keep_awake] 正在恢复所有设置...")
    finally:
        reset_execution_state()
        enable_lock_screen()
        print("[keep_awake] 已停止，所有设置已恢复")


if __name__ == "__main__":
    main()
