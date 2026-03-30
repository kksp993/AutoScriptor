import json
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import hmac
import hashlib
from AutoScriptor.utils.logger import logger

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
        """保存加密配置到当前账号文件"""
        from AutoScriptor.utils.constant import cfg
        if cfg._account_data:
            cfg._account_data["encryption"] = self.config["encryption"]
            cfg._save_account_file()
        else:
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
        """更新游戏配置并加密敏感信息（兼容旧调用，character_name 不再加密）"""
        sensitive_data = {"account": account, "password": password}
        self.config["encryption"] = self.encrypt_data(sensitive_data, security_key)
        self._save_config()

    def decrypt_config(self, security_key: str) -> dict:
        """解密配置数据"""
        if not security_key or "encryption" not in self.config or not self.config["encryption"].get("encrypted_data"):
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

    @staticmethod
    def encrypt_data(data: dict, security_key: str) -> dict:
        """加密任意字典数据，返回加密元数据块（可复用于档案加密等场景）"""
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=500000,
        )
        key = kdf.derive(security_key.encode())
        plaintext = json.dumps(data).encode()
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted_data = ciphertext[:-16]
        tag = ciphertext[-16:]
        h = hmac.new(key, encrypted_data, hashlib.sha256)
        hmac_value = h.digest()
        return {
            "version": "1.0",
            "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "hmac": base64.b64encode(hmac_value).decode(),
            "encrypted_data": base64.b64encode(encrypted_data).decode(),
        }

    @staticmethod
    def decrypt_data(enc_block: dict, security_key: str) -> dict:
        """解密加密元数据块，返回原始字典。失败时抛出异常。"""
        salt = base64.b64decode(enc_block["salt"])
        nonce = base64.b64decode(enc_block["nonce"])
        tag = base64.b64decode(enc_block["tag"])
        encrypted_data = base64.b64decode(enc_block["encrypted_data"])
        stored_hmac = base64.b64decode(enc_block["hmac"])
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=500000,
        )
        key = kdf.derive(security_key.encode())
        calculated_hmac = hmac.new(key, encrypted_data, hashlib.sha256).digest()
        if not hmac.compare_digest(calculated_hmac, stored_hmac):
            raise ValueError("数据完整性验证失败")
        aesgcm = AESGCM(key)
        ciphertext = encrypted_data + tag
        decrypted_data = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(decrypted_data)