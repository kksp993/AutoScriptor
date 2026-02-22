"""
测试悬浮窗检测功能
支持两种模式:
  1. 离线模式: 用本地图片测试 (python test_floating_window.py --images img1.png img2.png)
  2. 在线模式: 实时截图测试 (python test_floating_window.py)
"""
import sys
import os
import io
import argparse
import time

# 修复 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from AutoScriptor.utils.box import Box
from AutoScriptor.recognition.floating_window import detect_floating_window


def test_with_images(image_paths: list[str], debug: bool = False):
    """用本地图片测试"""
    print(f"=== 离线测试模式: {len(image_paths)} 张图片 ===\n")
    for path in image_paths:
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            continue

        img = cv2.imread(path)
        if img is None:
            print(f"❌ 无法读取图片: {path}")
            continue

        print(f"📸 测试图片: {path} ({img.shape[1]}x{img.shape[0]})")

        t0 = time.perf_counter()
        result = detect_floating_window(img, debug=debug)
        elapsed = (time.perf_counter() - t0) * 1000

        if result["found"]:
            print(f"  ✅ 发现悬浮窗!")
            print(f"     边缘: {result['edge']}")
            print(f"     位置: {result['box']}")
            print(f"     中心: {result['center']}")
            print(f"     面积: {result['area']}px²")
            print(f"     绿色占比: {result['green_ratio']:.1%}")
            print(f"     耗时: {elapsed:.1f}ms")

            # 在图片上标注结果
            box = result["box"]
            annotated = img.copy()
            cv2.rectangle(
                annotated,
                (box.left, box.top),
                (box.left + box.width, box.top + box.height),
                (0, 255, 0),
                2,
            )
            cv2.putText(
                annotated,
                f"{result['edge']} ({result['area']}px2)",
                (box.left, box.top - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
            )
            out_path = path.rsplit(".", 1)[0] + "_detected.png"
            cv2.imwrite(out_path, annotated)
            print(f"     标注图已保存: {out_path}")
        else:
            print(f"  ⚠️  未检测到悬浮窗 (耗时: {elapsed:.1f}ms)")

        print()


def test_realtime(count: int = 5, debug: bool = False):
    """实时截图测试"""
    from AutoScriptor import mixctrl

    print(f"=== 实时测试模式: 连续截图 {count} 次 ===\n")

    for i in range(count):
        screenshot = mixctrl.screenshot()
        if screenshot is None:
            print(f"❌ 截图失败 (第{i+1}次)")
            continue

        t0 = time.perf_counter()
        result = detect_floating_window(screenshot, debug=debug)
        elapsed = (time.perf_counter() - t0) * 1000

        if result["found"]:
            print(
                f"[{i+1}/{count}] ✅ {result['edge']}边 "
                f"box={result['box']} "
                f"area={result['area']}px² "
                f"green={result['green_ratio']:.1%} "
                f"({elapsed:.1f}ms)"
            )
        else:
            print(f"[{i+1}/{count}] ⚠️  未检测到 ({elapsed:.1f}ms)")

        if debug and screenshot is not None:
            out_path = os.path.join("logs", "debug", "floating_window", f"screenshot_{i}.png")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            cv2.imwrite(out_path, screenshot)

        time.sleep(0.5)


def test_with_templates():
    """用现有悬浮窗模板图片验证绿色检测"""
    template_dir = os.path.join(os.getcwd(), "ZmxyOL", "assets", "pic")
    templates = [
        "xuanfuchuang-shang@0#-1#1280#14.png",
        "xuanfuchuang-shang@0#0#1280#720.png",
        "xuanfuchuang-xia@0#0#1280#720.png",
        "xuanfuchuang-zuo@0#0#1280#720.png",
        "xuanfuchuang-you@0#0#1280#720.png",
        "xuanfuchuang@0#0#1280#720.png",
    ]

    print("=== 模板绿色特征验证 ===\n")
    for name in templates:
        path = os.path.join(template_dir, name)
        if not os.path.exists(path):
            print(f"  ❌ 模板不存在: {name}")
            continue
        img = cv2.imread(path)
        if img is None:
            continue

        # 分析模板的HSV绿色占比
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array([35, 60, 60], dtype=np.uint8)
        upper = np.array([90, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        green_pixels = cv2.countNonZero(mask)
        total_pixels = img.shape[0] * img.shape[1]
        ratio = green_pixels / max(total_pixels, 1)
        print(
            f"  {name}: {img.shape[1]}x{img.shape[0]} "
            f"绿色像素={green_pixels}/{total_pixels} ({ratio:.1%})"
        )
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="悬浮窗检测测试")
    parser.add_argument("--images", nargs="+", help="本地图片路径（离线测试）")
    parser.add_argument("--realtime", action="store_true", help="实时截图测试")
    parser.add_argument("--count", type=int, default=5, help="实时模式截图次数")
    parser.add_argument("--debug", action="store_true", help="保存调试图像")
    parser.add_argument("--templates", action="store_true", help="验证模板绿色特征")
    args = parser.parse_args()

    if args.templates:
        test_with_templates()
    elif args.images:
        test_with_images(args.images, debug=args.debug)
    elif args.realtime:
        test_realtime(count=args.count, debug=args.debug)
    else:
        # 默认：先验证模板，再实时测试
        test_with_templates()
        print("---\n")
        test_realtime(debug=args.debug)
