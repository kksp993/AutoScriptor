"""
基于 manifest 的内容增量更新（bsdiff + 整文件）
============================================
从 HTTPS 拉取 manifest.json，下载补丁或整文件，校验后写入安装根目录。

配置清单地址（任选其一）：
- 环境变量 AUTOSCRIPTOR_CONTENT_MANIFEST_URL = 完整 manifest.json 的 URL
- 项目根目录 config.json 中 deploy.content_manifest_url（若存在）

本地当前内容版本：.autoscriptor/content_version.json
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any

from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_app_root, get_data_root

from services.core.binary_delta import (
    apply_bsdiff_patch,
    atomic_write_file,
    resolve_safe_path,
    sha256_file,
)
from services.core.content_update_security import (
    apply_security_checks_after_parse,
    fetch_bytes_limited,
    max_manifest_bytes,
    max_patch_bytes,
    max_raw_bytes,
    verify_manifest_sha256_if_configured,
)

try:
    from packaging.version import parse as parse_version
except Exception:  # pragma: no cover
    parse_version = None


def _compare_versions(local: str, remote: str) -> int:
    """返回 <0 若 local 更旧，0 相同，>0 若 local 更新。"""
    if parse_version is not None:
        try:
            a, b = parse_version(local), parse_version(remote)
            if a < b:
                return -1
            if a > b:
                return 1
            return 0
        except Exception:
            pass
    if local == remote:
        return 0
    return -1 if local < remote else 1


class ContentDeltaUpdater:
    """内容增量更新（与 Git updater 独立）。"""

    state: str = "idle"
    last_error: str = ""
    remote_manifest: dict[str, Any] | None = None

    def __init__(self, root: str | None = None, config_path: str | None = None):
        self._root = root or str(get_app_root())
        if config_path is not None:
            self._config_path = config_path
        elif root is not None:
            self._config_path = os.path.join(self._root, "config.json")
        else:
            self._config_path = str(get_data_root() / "config.json")
        self._lock = threading.Lock()

    def _version_file(self) -> str:
        return os.path.join(self._root, ".autoscriptor", "content_version.json")

    def _load_config_json(self) -> dict[str, Any]:
        cfg_path = self._config_path
        if not os.path.isfile(cfg_path):
            cfg_path = os.path.join(self._root, "config.json")
        if not os.path.isfile(cfg_path):
            return {}
        try:
            with open(cfg_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_config_manifest_url(self) -> str | None:
        deploy = self._load_config_json().get("deploy") or {}
        url = deploy.get("content_manifest_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
        return None

    def _apply_cooldown_path(self) -> str:
        return os.path.join(self._root, ".autoscriptor", "last_apply_attempt.json")

    def _apply_cooldown_sec(self) -> float:
        env = os.environ.get("AUTOSCRIPTOR_CONTENT_APPLY_COOLDOWN_SEC", "").strip()
        if env:
            try:
                return max(60.0, float(env))
            except ValueError:
                pass
        deploy = self._load_config_json().get("deploy") or {}
        v = deploy.get("content_update_apply_cooldown_sec")
        if isinstance(v, (int, float)) and float(v) >= 60.0:
            return float(v)
        return 180.0

    def _cooldown_read_ts(self) -> float | None:
        p = self._apply_cooldown_path()
        if not os.path.isfile(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return float(json.load(f).get("ts", 0))
        except Exception:
            return None

    def _cooldown_write_ts(self) -> None:
        p = self._apply_cooldown_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time()}, f, indent=2)

    def apply_cooldown_remaining_sec(self) -> float:
        """全机安装级冷却：距离允许再次「应用」更新的剩余秒数。"""
        cd = self._apply_cooldown_sec()
        last = self._cooldown_read_ts()
        if last is None:
            return 0.0
        rem = cd - (time.time() - last)
        return max(0.0, rem)

    def _deploy_content_trust_settings(self) -> tuple[str | None, str | None, str | None]:
        """
        返回 (可选 manifest 整包 sha256, 可选 PEM 字符串, 可选公钥文件路径已解析)。
        """
        deploy = self._load_config_json().get("deploy") or {}
        msha = deploy.get("content_manifest_sha256")
        pem = deploy.get("content_update_public_key_pem")
        ppath = deploy.get("content_update_public_key_path")
        msha_s = msha.strip().lower() if isinstance(msha, str) and msha.strip() else None
        pem_s = pem.strip() if isinstance(pem, str) and pem.strip() else None
        path_resolved: str | None = None
        if isinstance(ppath, str) and ppath.strip():
            raw = ppath.strip()
            path_resolved = raw if os.path.isabs(raw) else os.path.join(self._root, raw)
        return msha_s, pem_s, path_resolved

    def requires_credential_unlock(self) -> bool:
        """是否在应用内容更新前要求安全凭据解锁（与执行自动化相同）。"""
        deploy = self._load_config_json().get("deploy") or {}
        v = deploy.get("content_update_require_credential_unlock", False)
        if os.environ.get("AUTOSCRIPTOR_CONTENT_UPDATE_REQUIRE_CREDENTIAL_UNLOCK", "").strip() in (
            "1",
            "true",
            "yes",
        ):
            return True
        return bool(v)

    def get_manifest_url(self) -> str | None:
        env = os.environ.get("AUTOSCRIPTOR_CONTENT_MANIFEST_URL", "").strip()
        if env:
            return env
        return self._load_config_manifest_url()

    def get_local_content_version(self) -> str:
        p = self._version_file()
        if not os.path.isfile(p):
            return "0.0.0"
        try:
            with open(p, encoding="utf-8") as f:
                j = json.load(f)
            v = j.get("content_version")
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            pass
        return "0.0.0"

    def set_local_content_version(self, version: str) -> None:
        os.makedirs(os.path.dirname(self._version_file()), exist_ok=True)
        with open(self._version_file(), "w", encoding="utf-8") as f:
            json.dump({"content_version": version}, f, ensure_ascii=False, indent=2)

    def fetch_manifest(self) -> dict[str, Any] | None:
        url = self.get_manifest_url()
        if not url:
            self.last_error = "未配置清单 URL（AUTOSCRIPTOR_CONTENT_MANIFEST_URL 或 deploy.content_manifest_url）"
            return None
        try:
            msha_cfg, pem, pem_path = self._deploy_content_trust_settings()
            raw = fetch_bytes_limited(
                url, max_manifest_bytes(), expected_sha256=None, timeout=30
            )
            verify_manifest_sha256_if_configured(raw, expected_hex=msha_cfg)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                self.last_error = "manifest 不是 JSON 对象"
                return None
            apply_security_checks_after_parse(
                data, public_key_pem=pem, public_key_path=pem_path
            )
            self.remote_manifest = data
            self.last_error = ""
            return data
        except Exception as e:
            self.last_error = str(e)
            logger.warning(f"拉取 manifest 失败: {e}")
            return None

    def check_has_update(self) -> tuple[bool, str]:
        """
        返回 (是否有新版本, 说明)。
        """
        m = self.fetch_manifest()
        if m is None:
            return False, self.last_error or "无法获取 manifest"
        remote = m.get("content_version")
        if not isinstance(remote, str) or not remote.strip():
            return False, "manifest 缺少 content_version"
        local = self.get_local_content_version()
        cmp = _compare_versions(local, remote.strip())
        if cmp < 0:
            return True, f"{local} -> {remote.strip()}"
        return False, f"已是最新 ({local})"

    def apply_manifest(self, manifest: dict[str, Any] | None = None) -> bool:
        """
        下载并应用 manifest 中的全部 artifacts。成功后将本地 content_version 设为远程版本。
        """
        with self._lock:
            self.state = "applying"
            self.last_error = ""
            try:
                m = manifest or self.remote_manifest or self.fetch_manifest()
                if m is None:
                    self.state = "failed"
                    return False
                _, pem_trust, pem_path_trust = self._deploy_content_trust_settings()
                apply_security_checks_after_parse(
                    m, public_key_pem=pem_trust, public_key_path=pem_path_trust
                )
                remote_ver = m.get("content_version")
                if not isinstance(remote_ver, str) or not remote_ver.strip():
                    raise ValueError("manifest 缺少 content_version")
                remote_ver = remote_ver.strip()

                local_v = self.get_local_content_version()
                vcmp = _compare_versions(local_v, remote_ver)
                if vcmp == 0:
                    raise ValueError("本地已与 manifest 内容版本一致，无需应用")
                if vcmp > 0:
                    raise ValueError("manifest 内容版本低于本地，拒绝降级")

                arts = m.get("artifacts")
                if not isinstance(arts, list):
                    raise ValueError("manifest 缺少 artifacts 数组")

                cd = self._apply_cooldown_sec()
                now = time.time()
                last_ts = self._cooldown_read_ts()
                if last_ts is not None and now - last_ts < cd:
                    raise ValueError(
                        f"请等待 {int(cd - (now - last_ts))} 秒后再应用更新"
                    )
                self._cooldown_write_ts()

                for i, art in enumerate(arts):
                    if not isinstance(art, dict):
                        raise ValueError(f"artifacts[{i}] 不是对象")
                    kind = art.get("kind")
                    rel = art.get("relative_path")
                    url = art.get("url")
                    if kind not in ("bsdiff", "raw"):
                        raise ValueError(f"未知 kind: {kind}")
                    if not isinstance(rel, str) or not rel.strip():
                        raise ValueError(f"artifacts[{i}] 缺少 relative_path")
                    if not isinstance(url, str) or not url.strip():
                        raise ValueError(f"artifacts[{i}] 缺少 url")

                    try:
                        target = resolve_safe_path(self._root, rel)
                    except ValueError as e:
                        raise ValueError(str(e)) from e

                    if kind == "bsdiff":
                        old_h = art.get("old_sha256")
                        new_h = art.get("new_sha256")
                        patch_h = art.get("patch_sha256")
                        if not all(isinstance(x, str) and len(x) == 64 for x in (old_h, new_h, patch_h)):
                            raise ValueError(f"artifacts[{i}] bsdiff 需要 old_sha256/new_sha256/patch_sha256")
                        if not os.path.isfile(target):
                            raise FileNotFoundError(f"要打补丁的本地文件不存在: {target}")
                        if sha256_file(target).lower() != old_h.lower():
                            raise ValueError(
                                f"本地文件与 old_sha256 不一致（是否跳过版本？）: {rel}"
                            )
                        patch_data = fetch_bytes_limited(
                            url, max_patch_bytes(), expected_sha256=patch_h, timeout=300
                        )
                        d = os.path.dirname(target) or "."
                        fd, ptmp = tempfile.mkstemp(prefix=".bsdiff_", suffix=".patch", dir=d)
                        os.close(fd)
                        try:
                            with open(ptmp, "wb") as f:
                                f.write(patch_data)
                            apply_bsdiff_patch(
                                target, ptmp, target, expected_new_sha256=new_h
                            )
                        finally:
                            if os.path.isfile(ptmp):
                                try:
                                    os.remove(ptmp)
                                except OSError:
                                    pass
                        logger.info(f"已应用 bsdiff: {rel}")
                    else:
                        raw_h = art.get("sha256")
                        if not isinstance(raw_h, str) or len(raw_h) != 64:
                            raise ValueError(f"artifacts[{i}] raw 需要 sha256")
                        data = fetch_bytes_limited(
                            url, max_raw_bytes(), expected_sha256=raw_h, timeout=300
                        )
                        atomic_write_file(target, data)
                        logger.info(f"已写入整文件: {rel}")

                self.set_local_content_version(remote_ver)
                self.state = "done"
                logger.info(f"内容更新完成: content_version={remote_ver}")
                return True
            except Exception as e:
                self.last_error = str(e)
                self.state = "failed"
                logger.error(f"内容增量更新失败: {e}")
                return False

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "content_version_local": self.get_local_content_version(),
            "manifest_url": self.get_manifest_url(),
            "last_error": self.last_error,
            "apply_cooldown_remaining_sec": round(self.apply_cooldown_remaining_sec(), 1),
            "remote_content_version": (
                self.remote_manifest.get("content_version")
                if isinstance(self.remote_manifest, dict)
                else None
            ),
        }


content_delta_updater = ContentDeltaUpdater()
