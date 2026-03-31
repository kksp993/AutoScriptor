from AutoScriptor import *
import time
import getpass
from dataclasses import dataclass
from AutoScriptor.utils.logger import logger

# ── 通用页面路由器（可复用于登录、导航等多种页面流程） ──

class PageRouter:
    """
    页面状态机：注册页面标记 → 循环检测 → 分发处理。

    状态由 (name, tag) 组成，tag 默认为 None。
    同一页面注册不同 tag 可产生不同状态，互不阻断重入。

    用法::

        router = PageRouter()

        @router.page("主页", T("首页"), I("logo"))
        def on_home(ctx):
            click(T("设置"))

        @router.page("设置页", T("设置"), tag="confirm")
        def on_settings(ctx):
            ctx.done = True

        router.run(ctx, initial_timeout=30)
    """

    def __init__(self):
        self._pages = []

    def page(self, name, *markers, tag=None):
        """装饰器：注册页面名称、tag、识别标记（Target）和处理函数。"""
        def decorator(fn):
            self._pages.append((name, tag, markers, fn))
            return fn
        return decorator

    @property
    def all_markers(self):
        """所有已注册页面的标记合集（用于 locate 一次性等待）。"""
        return tuple(m for _, _, markers, _ in self._pages for m in markers)

    def detect(self, boxes, prev_state=None):
        """
        从 locate 返回的 boxes 直接判断当前页面，无需再次截图识别。
        boxes 与 all_markers 索引对齐；按注册顺序优先匹配，优先返回非上次状态。
        """
        fallback = None
        idx = 0
        for name, tag, markers, handler in self._pages:
            n = len(markers)
            if any(boxes[idx + j] for j in range(n)):
                state = (name, tag)
                if state != prev_state:
                    return state, handler
                if fallback is None:
                    fallback = (state, handler)
            idx += n
        return fallback

    def run(self, ctx=None, *, initial_timeout=120, step_timeout=20,
            max_steps=30, is_done=lambda c: getattr(c, 'done', False)):
        """
        主循环：等待任意页面出现 → 识别具体页面 → 执行 handler → 重复。

        首轮使用 initial_timeout（适配冷启动），后续使用 step_timeout。
        """
        for step in range(max_steps):
            timeout = initial_timeout if step == 0 else step_timeout
            boxes = locate(self.all_markers, timeout=timeout, assure_stable=False, is_simplify=False)
            result = self.detect(boxes or [], prev_state=ctx.prev_state)
            if result is None:
                raise TimeoutError(f"页面检测超时 ({timeout}s)")
            state, handler = result
            ctx.prev_state = state
            name, tag = state
            logger.info(f"[PageRouter] {name}" + (f"[{tag}]" if tag else ""))
            handler(ctx)
            if is_done(ctx):
                return
        raise RuntimeError(f"PageRouter: 超过最大步数 ({max_steps})")


# ── 登录上下文 ──

@dataclass
class LoginCtx:
    # 仅保存“入口传参”，不预先解密，实现到用时才解密
    account: str = None
    password: str = None
    character_name: str = None
    character_index: int = 0
    done: bool = False
    prev_state: tuple = None

    # 缓存解密后的账号信息，避免多次弹窗
    _loaded: bool = False

    def ensure_loaded(self):
        """如有必要，解密并加载账密等配置，仅在真正用到时触发。"""
        if self._loaded:
            return
        if not self.account or not self.password:
            cfg.load_config(getpass.getpass("请输入 安全密码: "))
            self.account = cfg["game"].get("account", None)
            self.password = cfg["game"].get("password", None)
            if not self.character_name:
                self.character_name = cfg["game"].get("character_name", None)
        self._loaded = True


# ── 辅助函数 ──

def _fill_account_password(ctx_or_account, password = None):
    """填入账号密码并登录

    ctx_or_account: 可以是 LoginCtx，也可以是两参数模式
    """
    if isinstance(ctx_or_account, LoginCtx):
        ctx = ctx_or_account
        ctx.ensure_loaded()
        account, password = ctx.account, ctx.password
    else:
        account = ctx_or_account
    click(T("请输入手机号或用户名"), if_exist=True, timeout=5)
    input(account)
    click(T("请输入密码"), if_exist=True)
    input(password)
    # Agree to terms checkbox (may already be checked)
    click(T("我已同意"), if_exist=True, timeout=2)
    click(T("登录", box=Box(23,487,674,62).margin()), timeout=5)
    time.sleep(1)


def _handle_post_login_popups():
    """Dismiss popups that appear between login and character selection."""
    click(T("同意并登录", color="青色", box=Box(160, 707, 442, 95)), if_exist=True, timeout=3)
    click(T("授权并登录"), if_exist=True, timeout=3)


def _select_character(character_name, character_index):
    """Select character and enter game."""
    click(T("开心收下"), if_exist=True, timeout=3)
    click(B(640, 575), if_exist=True)

    if character_index:
        sleep(1)
        if character_index <= 5:
            click(B(104, 63 + 70 * (character_index - 1), 149, 54))
        else:
            click(B(104, 516, 63, 26))
            sleep(1)
            click(B(104, 63 + 70 * (character_index - 6), 149, 54))
    elif character_name:
        click(T(character_name), delay=1, timeout=60)
    else:
        name = cfg["game"].get("character_name")
        if not name:
            raise ValueError("请先配合完成安全密码验证")
        click(T(name), delay=1)

    click(B(640, 580), if_exist=True)
    click(T("进入游戏", color="橙色"), timeout=10)

    if ui_T(T("确定"), 3):
        click(T("确定"))
        return False  # need to re-login
    wait_for_appear(I("加载中"), timeout=10)
    locate(I("活动公告页面"), 30)
    click(B(1240, 5, 40, 60))
    time.sleep(0.5)
    dismiss_floating_window(max_retries=1, debug=False)
    if ui_T(T("精彩活动"), 3):
        click(B(1100, 40, 40, 40))
    logger.info("登录完成")
    return True



# ── 登录页面注册 ──

_login = PageRouter()


@_login.page("角色选择", T("进入游戏", color="橙色"))
def _on_character_select(ctx):
    _select_character(ctx.character_name, ctx.character_index)
    ctx.done = True

@_login.page("初始授权", T("已阅读并同意"))
def _on_authorization(ctx):
    click(T("账号登录"), if_exist=True)
    click(T("已阅读并同意"))
    click(B(719, 536, 144, 26), if_exist=True)
    click(T("授权并登录"), if_exist=True, timeout=3)
    click(T("添加账号"), if_exist=True, timeout=3)
    time.sleep(1)
    if ui_T(T("请输入手机号或用户名"), 3) or ui_T(T("账号密码登录"), 3):
        click(T("账号登录"), if_exist=True, delay=1)
        _fill_account_password(ctx)
    _handle_post_login_popups()


@_login.page("账号密码登录", T("账号密码登录"))
def _on_password_login(ctx):
    _fill_account_password(ctx)
    _handle_post_login_popups()


@_login.page("快速登录", T("手机号登录"), T("账号登录"))
def _on_quick_login(ctx):
    click(T("账号登录"))
    time.sleep(1)
    if ui_T(T("账号密码登录"), 5) or ui_T(T("请输入手机号或用户名"), 5):
        _fill_account_password(ctx)
    else:
        logger.warning("未能切换到账号密码页，尝试快速登录")
        click(T("登录", color="绿色"), if_exist=True)
    _handle_post_login_popups()




# ── 登录入口 ──
def login(account: str = None, password: str = None,
          character_name: str = None, character_index: int = 0):
    """4399 登录全流程（页面状态机驱动）。仅在用到账密时才触发解密。"""
    ctx = LoginCtx(account, password, character_name, character_index)
    _login.run(ctx)


if __name__ == "__main__":
    # 不预先解密，直到首次用到账密才弹窗
    login(
        None,
        None,
        None,
    )
