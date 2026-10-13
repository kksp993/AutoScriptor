"""实验室安全教育平台 —— 刷学习时长（大屏表格版式，**写死坐标**）。

坐标标定依据（720x1280，MuMu 15.0，页面 = 考试页「大屏」版式；证据见
logs/dsh_scratch/cal4_report.txt / cal6_report.txt）：

  表格：15 行/页，每行右侧「去学习」按钮统一在 x=623，行 y 中心 =
      591, 636, 679, 724, 769, 813, 857, 901, 944, 989, 1033, 1077, 1121, 1165, 1209
  点「去学习」→ 文章态，左上「返回」在 (214, 488)；点「返回」回到表格（仍在该页）
  翻页：点 (545, 1250)（下一页）

  危险区（绝不点击）：模拟考试(689,321) / 开始考试(688,355)

环境变量：
  LAB_DWELL    每条停留秒数，默认 121（原脚本 countdown(2,1) 的时长）
  LAB_MINUTES  最长运行分钟数，默认 120（本次 4h 用 240）
  LAB_PAGES    最多翻多少页，默认 12（平台共 168 条 = 12 页）

倒计时输出已删除（改为静默 sleep）。
"""
from AutoScriptor import *
from AutoScriptor.utils.logger import logger
import os
import time
import traceback

# ---- 标定后的写死坐标 ----
ROWS_Y = [591, 636, 679, 724, 769, 813, 857, 901, 944, 989, 1033, 1077, 1121, 1165, 1209]
STUDY_X = 623                 # 「去学习」按钮列
BACK_PT = B(214, 488)         # 文章态「返回」
NEXT_PAGE_PT = B(545, 1250)   # 下一页

DWELL_SECONDS = int(os.environ.get("LAB_DWELL", "121"))
MAX_MINUTES = float(os.environ.get("LAB_MINUTES", "120"))
MAX_PAGES = int(os.environ.get("LAB_PAGES", "12"))


def study():
    """每条文章的停留时间（静默，不打印倒计时）。"""
    sleep(DWELL_SECONDS)


def next_one(y: int):
    """点这一行的「去学习」→ 停留 → 点「返回」。"""
    click(B(STUDY_X, y))
    study()
    click(BACK_PT)


def next_page():
    """翻到下一页。"""
    click(NEXT_PAGE_PT)


def main_loop():
    deadline = time.perf_counter() + MAX_MINUTES * 60
    for page in range(1, MAX_PAGES + 1):
        for idx, y in enumerate(ROWS_Y, 1):
            if time.perf_counter() >= deadline:
                logger.info(f"到达最长运行时间 {MAX_MINUTES:g} 分钟，停止（第 {page} 页第 {idx} 条）")
                return
            logger.info(f"[第{page}页 {idx}/{len(ROWS_Y)}] 去学习 y={y}")
            next_one(y)
        if time.perf_counter() >= deadline:
            logger.info(f"到达最长运行时间 {MAX_MINUTES:g} 分钟，停止（第 {page} 页已完成）")
            return
        logger.info(f"第 {page} 页完成，翻页")
        next_page()
        sleep(3)
    logger.info(f"已翻完 {MAX_PAGES} 页，停止")


if __name__ == "__main__":
    try:
        main_loop()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
