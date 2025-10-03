import json
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import hmac
import hashlib
from logzero import logger

class ConfigManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self._load_config()
        
    def _load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "emulator": {
                    "index": 1,
                    "adb_addr": "127.0.0.1:16416"
                },
                "encryption": {
                    "version": "1.0",
                    "salt": "",
                    "nonce": "",
                    "tag": "",
                    "encrypted_data": ""
                }
            }
            self._save_config()

    def _save_config(self):
        """保存配置文件"""
        from AutoScriptor.utils.constant import cfg
        cfg["encryption"] = self.config["encryption"]
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def _generate_key(self, password: str, salt: bytes) -> bytes:
        """从密码生成密钥"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # AES-256 需要32字节密钥
            salt=salt,
            iterations=500000,  # 增加迭代次数以提高安全性
        )
        return kdf.derive(password.encode())

    def _generate_hmac(self, data: bytes, key: bytes) -> bytes:
        """生成HMAC用于数据完整性验证"""
        h = hmac.new(key, data, hashlib.sha256)
        return h.digest()

    def update_game_config(self, account: str, password: str, character_name: str, security_key: str):
        """更新游戏配置并加密敏感信息"""
        # 生成随机盐值
        salt = secrets.token_bytes(16)
        # 生成随机nonce
        nonce = secrets.token_bytes(12)
        
        # 生成加密密钥
        key = self._generate_key(security_key, salt)
        
        # 准备要加密的数据
        sensitive_data = {
            "account": account,
            "password": password,
            "character_name": character_name
        }
        
        # 序列化数据
        data = json.dumps(sensitive_data).encode()
        
        # 使用AES-GCM进行加密
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        
        # 分离密文和认证标签
        encrypted_data = ciphertext[:-16]
        tag = ciphertext[-16:]
        
        # 生成HMAC用于数据完整性验证
        hmac_value = self._generate_hmac(encrypted_data, key)
        
        # 保存加密相关信息
        self.config["encryption"] = {
            "version": "1.0",
            "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "hmac": base64.b64encode(hmac_value).decode(),
            "encrypted_data": base64.b64encode(encrypted_data).decode()
        }
        
        self._save_config()

    def decrypt_config(self, security_key: str) -> dict:
        """解密配置数据"""
        if "encryption" not in self.config or not self.config["encryption"].get("encrypted_data"):
            return {}
            
        try:
            # 获取加密相关信息
            salt = base64.b64decode(self.config["encryption"]["salt"])
            nonce = base64.b64decode(self.config["encryption"]["nonce"])
            tag = base64.b64decode(self.config["encryption"]["tag"])
            encrypted_data = base64.b64decode(self.config["encryption"]["encrypted_data"])
            stored_hmac = base64.b64decode(self.config["encryption"]["hmac"])
            
            # 生成密钥
            key = self._generate_key(security_key, salt)
            
            # 验证HMAC
            calculated_hmac = self._generate_hmac(encrypted_data, key)
            if not hmac.compare_digest(calculated_hmac, stored_hmac):
                raise ValueError("数据完整性验证失败")
            
            # 使用AES-GCM进行解密
            aesgcm = AESGCM(key)
            ciphertext = encrypted_data + tag
            decrypted_data = aesgcm.decrypt(nonce, ciphertext, None)
            
            return json.loads(decrypted_data)
        except Exception as e:
            logger.error(f"解密失败: {str(e)}")
            return {} 