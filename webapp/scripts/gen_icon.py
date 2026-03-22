"""生成 webapp/icon.png：透明背景、大号绿色圆角块 + 橙色闪电。

高分辨率输出（默认 512），Electron 托盘会再缩放到 16×16，源图足够大才清晰。

依赖：Pillow（项目 venv 一般已装）。运行：python webapp/scripts/gen_icon.py
"""
from __future__ import annotations

import argparse
import os
import sys

# 品牌色（与用户参考图一致）
GREEN = (57, 181, 74, 255)  # ~#39b54a
ORANGE = (247, 147, 30, 255)  # ~#f7931e

# 闪电轮廓（归一化，中心为 0,0；竖向略偏上，视觉更稳）
_LIGHTNING = [
    (0.0, -0.48),
    (0.24, -0.06),
    (0.06, 0.02),
    (0.44, 0.52),
    (-0.06, 0.12),
    (-0.32, -0.26),
    (-0.08, -0.36),
]


def _render_internal(draw_size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (draw_size, draw_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绿色块占画布约 86%，居中
    m = draw_size * 0.07
    w = h = draw_size - 2 * m
    x0, y0 = m, m
    corner_r = min(w, h) * 0.24

    draw.rounded_rectangle(
        (x0, y0, x0 + w, y0 + h),
        radius=corner_r,
        fill=GREEN,
    )

    cx = x0 + w / 2
    cy = y0 + h / 2
    scale = min(w, h) * 0.42
    poly = [(cx + px * scale, cy + py * scale) for px, py in _LIGHTNING]
    draw.polygon(poly, fill=ORANGE)

    return img


def render_icon(export_size: int = 512, internal_size: int = 1024):
    """先在高分辨率光栅上绘制，再 Lanczos 缩放到目标尺寸，边缘更顺滑。"""
    from PIL import Image

    if internal_size < export_size:
        internal_size = export_size * 2
    big = _render_internal(internal_size)
    return big.resize((export_size, export_size), Image.Resampling.LANCZOS)


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：pip install Pillow", file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser(description="生成透明背景的应用图标 PNG")
    ap.add_argument(
        "-s",
        "--size",
        type=int,
        default=512,
        help="导出边长（像素），默认 512",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出路径，默认 webapp/icon.png",
    )
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.output or os.path.join(root, "icon.png")

    im = render_icon(export_size=args.size)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    im.save(out, "PNG", optimize=True)
    print("Wrote", out, im.size)


if __name__ == "__main__":
    main()
