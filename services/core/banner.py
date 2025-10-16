# ANSI 颜色（在 Windows 上通过 colorama 启用）
import shutil


try:
    import colorama  # type: ignore
    colorama.just_fix_windows_console()
except Exception:
    pass

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
GREEN = "\033[92m"
WHITE = "\033[97m"

def _render_center_line(content: str, inner_width: int, color_prefix: str = "", bold: bool = False) -> str:
    """渲染一行带左右边框且居中的文本。颜色只包裹内容，不影响对齐计算。"""
    raw = content.strip()
    if len(raw) > inner_width:
        raw = raw[:inner_width]
    padding = inner_width - len(raw)
    left = padding // 2
    right = padding - left
    prefix = (BOLD if bold else "") + (color_prefix or "")
    suffix = RESET if prefix else ""
    return f"║{' ' * left}{prefix}{raw}{suffix}{' ' * right}║"

def _print_banner():
    """打印商业化风格的启动横幅，自动适配终端宽度。"""
    try:
        cols = shutil.get_terminal_size(fallback=(100, 24)).columns
    except Exception:
        cols = 100
    inner = max(72, min(cols - 4, 120))
    top = f"╔{'═' * inner}╗"
    bottom = f"╚{'═' * inner}╝"
      # 使用 Socket.IO 服务器以支持 WebSocket
    print("------------------------------"*4)
    print("""
  ______               __                 ______                       __              __                               
 /      \             /  |               /      \                     /  |            /  |                              
/$$$$$$  | __    __  _$$ |_     ______  /$$$$$$  |  _______   ______  $$/   ______   _$$ |_     ______    ______        
$$ |__$$ |/  |  /  |/ $$   |   /      \ $$ \__$$/  /       | /      \ /  | /      \ / $$   |   /      \  /      \       
$$    $$ |$$ |  $$ |$$$$$$/   /$$$$$$  |$$      \ /$$$$$$$/ /$$$$$$  |$$ |/$$$$$$  |$$$$$$/   /$$$$$$  |/$$$$$$  |      
$$$$$$$$ |$$ |  $$ |  $$ | __ $$ |  $$ | $$$$$$  |$$ |      $$ |  $$/ $$ |$$ |  $$ |  $$ | __ $$ |  $$ |$$ |  $$/       
$$ |  $$ |$$ \__$$ |  $$ |/  |$$ \__$$ |/  \__$$ |$$ \_____ $$ |      $$ |$$ |__$$ |  $$ |/  |$$ \__$$ |$$ |            
$$ |  $$ |$$    $$/   $$  $$/ $$    $$/ $$    $$/ $$       |$$ |      $$ |$$    $$/   $$  $$/ $$    $$/ $$ |            
$$/   $$/  $$$$$$/     $$$$/   $$$$$$/   $$$$$$/   $$$$$$$/ $$/       $$/ $$$$$$$/     $$$$/   $$$$$$/  $$/             
                                                                          $$ |                                          
                                                                          $$ |                                          
                                                                          $$/                  
    """)
    print()
    print(f"{MAGENTA}{top}{RESET}")
    print(_render_center_line("AutoScriptor", inner, WHITE, True))
    print(_render_center_line("ZmxyOL - WebUI", inner, CYAN, True))
    print(_render_center_line("Version 0.1.0   |   Author: Kksp993", inner, WHITE, False))
    print(_render_center_line("Repo: https://github.com/kksp993/AutoScriptor", inner, DIM, False))
    print(_render_center_line("Click to open: http://127.0.0.1:5000   (Ctrl+Click)", inner, YELLOW, True))
    print(f"{MAGENTA}{bottom}{RESET}")
    print()


if __name__ == "__main__":
    _print_banner()