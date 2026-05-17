from AutoScriptor import *
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
            # WebUI /api/verify 已用安全密码解密并驻留在 cfg 中；若此处再 getpass，
            # 在 Electron/无 TTY 下常得到空串 → load_config("") 会整表重载且不解密，反而清空账密。
            g = cfg._config.get("game") or {}
            if g.get("account") and g.get("password"):
                self.account = g["account"]
                self.password = g["password"]
                if not self.character_name:
                    self.character_name = g.get("character_name")
            else:
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
    click(B(611,220,26,26))
    click(B(612,304,25,26))
    click(T("请输入手机号或用户名"), if_exist=True, timeout=5)
    input(account)
    click(T("请输入密码"), if_exist=True)
    input(password)
    # Agree to terms checkbox (may already be checked)
    click(T("我已同意"), if_exist=True, timeout=2)
    click(T("登录", box=Box(23,487,674,62).margin()), timeout=5)
    sleep(1)


def _handle_post_login_popups():
    """Dismiss popups that appear between login and character selection."""
    click(T("同意并登录", color="青色", box=Box(160, 707, 442, 95)), if_exist=True, timeout=3)
    click(T("授权并登录"), if_exist=True, timeout=3)


def _select_character():
    """在角色选择页进入游戏；服务器与角色名仅来自已加载的 cfg['game']（Web 验证或 load_config 已写入），此处不解析、不触发解密。"""
    click(T("开心收下"), if_exist=True, timeout=3)
    click(B(640, 575), if_exist=True)

    g = cfg["game"]
    assert g.get("server_name") and g.get("character_name"), "请先配置服务器和角色"
    ensure_server(g["server_name"])
    ensure_character(g["character_name"])

    # 部分客户端，需要每次请求才给登录
    if first(get_colors(B(277,686,6,13))) != "绿色": click(B(277,686,6,13))

    click(T("进入游戏", color="橙色"), timeout=10)

    if ui_T(T("确定"), 3):
        click(T("确定"))
        return False  # need to re-login
    wait_for_appear(I("加载中"), timeout=10)
    locate(I("活动公告页面"), 30)
    click(B(1240, 5, 40, 60))
    sleep(0.5)
    dismiss_floating_window(max_retries=1, debug=False)
    if ui_T(T("精彩活动"), 3):
        click(B(1100, 40, 40, 40))
    logger.info("登录完成")
    return True



# ── 登录页面注册 ──

_login = PageRouter()


@_login.page("角色选择", T("进入游戏", color="橙色"))
def _on_character_select(ctx):
    _select_character()
    ctx.done = True

@_login.page("初始授权", T("已阅读并同意"))
def _on_authorization(ctx):
    click(T("账号登录"), if_exist=True)
    click(T("已阅读并同意"))
    click(B(719, 536, 144, 26), if_exist=True)
    click(T("授权并登录"), if_exist=True, timeout=3)
    click(T("添加账号"), if_exist=True, timeout=3)
    sleep(1)
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
    sleep(1)
    if ui_T(T("账号密码登录"), 5) or ui_T(T("请输入手机号或用户名"), 5):
        _fill_account_password(ctx)
    else:
        logger.warning("未能切换到账号密码页，尝试快速登录")
        click(T("登录", color="绿色"), if_exist=True)
    _handle_post_login_popups()

def ensure_server(server_name:str):
    switch_base("mumu")
    cur_server = extract_info(B(1007,49,232,30), post_process=lambda s: s.strip().replace("（","(").split("(")[0], ensure_not_empty=True)
    if cur_server != server_name:
        click(T("服务器", box=Box(1110,663,132,34).margin()))
        wait_for_appear(T("更换服务器", box=Box(532,110,217,38).margin()))
        while ui_F(T(server_name)):
            swipe(B(482,494), B(482,224))
        click(T(server_name))
        cnt = 0
        while cnt < 10:
            if server_name == extract_info(B(1007,49,232,30), post_process=lambda s: s.strip().replace("（","(").split("(")[0], ensure_not_empty=True):
                return
            cnt += 1
            sleep(1)
        raise Exception(f"当前服务器不是{server_name},当前服务器是{cur_server},请检查服务器是否正确")

def ensure_character(character_name:str):
    click(B(104,16,60,26))
    if ui_F(T(character_name, box=Box(17,54,254,433).margin())):
        click(B(104,516,63,26))
    if ui_F(T(character_name, box=Box(17,54,254,433).margin())):
        raise Exception(f"角色{character_name}不存在,请检查账户服务器是否正确")
    click(T(character_name, box=Box(17,54,254,433).margin()))



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
