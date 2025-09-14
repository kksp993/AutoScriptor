from AutoScriptor.utils.filter import get_selected_columns
from AutoScriptor.crypto.config_manager import ConfigManager
import os
from getpass import getpass
from logzero import logger

def mask_string(text: str, show_first: int = 1, show_last: int = 1) -> str:
    """
    对字符串进行掩码处理
    :param text: 原始字符串
    :param show_first: 显示前几位
    :param show_last: 显示后几位
    :return: 掩码后的字符串
    """
    if not text:
        return ""
    length = len(text)
    if length <= (show_first + show_last):
        return "*" * length
    
    return text[:show_first] + "*" * (length - show_first - show_last) + text[-show_last:]
# 获取配置文件路径
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),"config.json")
# 创建配置管理器实例
config_manager = ConfigManager(config_path)
def set_config():
    # 获取用户输入
    logger.info("请输入游戏配置信息：")
    os.system('cls' if os.name == 'nt' else 'clear')
    account = input("账号: ")
    password = getpass("密码: ")
    character_name = input("角色名称: ")
    security_key = getpass("安全密钥: ")
    
    # 更新配置
    config_manager.update_game_config(account, password, character_name, security_key)
    # 清屏
    os.system('cls' if os.name == 'nt' else 'clear')
    logger.info("配置已更新并加密！")
    
def verify_config():
    # 演示解密
    os.system('cls' if os.name == 'nt' else 'clear')
    logger.info("\n验证解密：")
    verify_key = getpass("请输入安全密钥进行解密: ")
    decrypted_data = config_manager.decrypt_config(verify_key)
    if decrypted_data:
        logger.info("解密成功！")
        logger.info(f"账号: {mask_string(decrypted_data['account'], 3, 4)}")  # 显示前2位和后2位
        logger.info(f"密码: {'*' * 8}")  # 密码完全隐藏
        logger.info(f"角色名称: {mask_string(decrypted_data['character_name'], 2, 1)}")  # 显示首尾各1位
    else:
        logger.info("解密失败！")

if __name__ == "__main__":
    res = get_selected_columns(avail_cols=["更新账号信息","验证账号配置"],prompt="请选择操作")[0]
    if res == "更新账号信息":
        set_config()
    elif res == "验证账号配置":
        verify_config()