from AutoScriptor.utils.filter import get_selected_columns
from AutoScriptor.crypto.config_manager import ConfigManager
import os
from getpass import getpass
from AutoScriptor.utils.logger import logger

def mask_string(text: str, show_first: int = 1, show_last: int = 1) -> str:
    if not text:
        return ""
    length = len(text)
    if length <= (show_first + show_last):
        return "*" * length
    return text[:show_first] + "*" * (length - show_first - show_last) + text[-show_last:]


def set_config():
    from AutoScriptor.utils.app_config import cfg
    if not cfg.current_account():
        logger.info("当前没有加载任何账号，请先通过 WebUI 创建账号")
        return

    logger.info("请输入游戏配置信息：")
    os.system('cls' if os.name == 'nt' else 'clear')
    account = input("账号: ")
    password = getpass("密码: ")
    security_key = getpass("安全密钥: ")

    sensitive = {"account": account, "password": password}
    cfg._account_data["encryption"] = ConfigManager.encrypt_data(sensitive, security_key)
    cfg._save_account_file()

    os.system('cls' if os.name == 'nt' else 'clear')
    logger.info("配置已更新并加密！")


def verify_config() -> dict | None:
    """验证并返回解密后的配置，失败返回 None"""
    from AutoScriptor.utils.app_config import cfg

    os.system('cls' if os.name == 'nt' else 'clear')
    logger.info("\n验证解密：")
    verify_key = getpass("请输入安全密钥进行解密: ")

    enc = cfg._account_data.get("encryption", {})
    if not enc.get("encrypted_data"):
        logger.info("当前账号没有加密数据")
        return None

    try:
        decrypted_data = ConfigManager.decrypt_data(enc, verify_key)
        logger.info("解密成功！")
        logger.info(f"账号: {mask_string(decrypted_data.get('account', ''), 3, 4)}")
        logger.info(f"密码: {'*' * 8}")
        return decrypted_data
    except Exception as e:
        logger.info(f"解密失败: {e}")
        return None


if __name__ == "__main__":
    res = get_selected_columns(avail_cols=["更新账号信息","验证账号配置"],prompt="请选择操作")[0]
    if res == "更新账号信息":
        set_config()
    elif res == "验证账号配置":
        verify_config()
