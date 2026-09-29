"""游戏内职业（与 battle_character 的脚本职业名区分，用于账号/界面配置）。"""

# 与游戏内可选职业一致，供 WebUI 下拉与 config 校验
GAME_PROFESSIONS: tuple[str, ...] = (
    "悟空",
    "唐僧",
    "沙僧",
    "八戒",
    "龙女",
    "王子",
    "嫦娥",
    "琉离",
    "白龙",
    "哪吒",
)

GAME_PROFESSION_SET = frozenset(GAME_PROFESSIONS)
DEFAULT_GAME_PROFESSION = GAME_PROFESSIONS[0]


def normalize_game_profession(raw: str | None) -> str:
    """Return a valid profession; blank means the configured default."""
    s = (raw or "").strip()
    if not s:
        return DEFAULT_GAME_PROFESSION
    if s not in GAME_PROFESSION_SET:
        raise ValueError(f"Unknown game profession: {s}")
    return s
