"""Script API release metadata, independent of application/package versions.

Keep this module dependency-free: querying a version must not load config,
OCR, game assets or device controls. See docs/AutoScriptor/reference/API.md.
"""

API_VERSION = "1.0.0"

API_VERSION_POLICY = (
    "这是 Python 脚本接口的版本，与软件版本分开记录。"
    "core/api.py 有较大的接口新增或修改时，小版本加 1，例如 v1.0.0 → v1.1.0。"
    "零碎改动先累计，也可按用户要求汇总发布。"
    "界面、教程和内部整理不改变 API 版本；影响旧脚本的改动会先确认迁移方案。"
)

# Add small public API changes here until the user requests a release, or a
# substantial API addition/change warrants one. Do not bump on every edit.
API_PENDING_CHANGES: tuple[str, ...] = ()

API_RELEASES = (
    {
        "version": "1.0.0",
        "date": "2026-11-16",
        "changes": (
            "建立现有脚本 API 的版本基线，已有脚本调用方式保持不变。",
            "新增 API_VERSION / get_api_version()，可在不初始化设备的情况下查询版本。",
        ),
    },
)


def get_api_version() -> str:
    """Return the script API version without initializing any runtime service."""
    return API_VERSION
