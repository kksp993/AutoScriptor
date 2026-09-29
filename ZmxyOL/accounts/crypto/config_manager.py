import json
import secrets
import binascii
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import hmac
import hashlib

DECRYPT_ERRORS = (KeyError, TypeError, ValueError, binascii.Error, InvalidTag)


class ConfigManager:
    DECRYPT_ERRORS = DECRYPT_ERRORS

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
