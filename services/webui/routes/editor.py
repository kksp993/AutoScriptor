"""
Editor API routes – WebUI 版图片编辑器后端
==========================================
提供截图获取、OCR、颜色识别、locate 校验、选区优化、保存等能力，
与前端 EditorPanel.js 配合使用。
"""

from __future__ import annotations

import base64
import os
import time
import traceback

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from AutoScriptor.utils.logger import logger

router = APIRouter(prefix="/api/editor", tags=["editor"])

# 缓存最近一次截图的 BGR ndarray，供 OCR / color / locate 复用
_last_screenshot: np.ndarray | None = None

_LOCATE_SCALES = [0.5, 0.75, 1.0]


def _locate_text_at_scale(screenshot, text, margin_box, color, scale):
    """在指定 scale 下测试 OCR locate，复用 locate_on_screen 的核心逻辑。"""
    from AutoScriptor.recognition.ocr_rec import ocr as _ocr
    from AutoScriptor.recognition.rec import get_box_color as _color
    from AutoScriptor.utils.box import Box

    roi = screenshot[margin_box.top:margin_box.top + margin_box.height,
                     margin_box.left:margin_box.left + margin_box.width]
    if roi.size == 0:
        return []

    found = _ocr(roi, [text], confidence=0.8, scale=scale)
    if not found or not found[0]:
        return []

    result_boxes = []
    for b in found[0]:
        fb = Box(b.left + margin_box.left, b.top + margin_box.top, b.width, b.height)
        if not fb.is_in(margin_box):
            continue
        if color and _color(screenshot, fb) != color:
            continue
        result_boxes.append(fb)
    return result_boxes


def _get_runtime():
    from services.core.runtime_context import runtime_ctx
    return runtime_ctx


def _screenshot_to_base64(img_bgr: np.ndarray) -> str:
    _, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── GET /api/editor/screenshot ──

@router.get("/screenshot")
async def editor_screenshot():
    global _last_screenshot
    try:
        ctx = _get_runtime()
        if ctx.mixctrl is None:
            return JSONResponse(status_code=503, content={"error": "mixctrl 未初始化"})
        img = ctx.mixctrl.screenshot()
        if img is None:
            return JSONResponse(status_code=500, content={"error": "截图返回空"})
        _last_screenshot = img
        h, w = img.shape[:2]
        return {"image": _screenshot_to_base64(img), "width": w, "height": h}
    except Exception as e:
        logger.error("editor/screenshot error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/ocr ──

@router.post("/ocr")
async def editor_ocr(request: Request):
    """对指定矩形区域执行 OCR，返回识别文本。"""
    global _last_screenshot
    try:
        data = await request.json()
        left, top, right, bottom = int(data["left"]), int(data["top"]), int(data["right"]), int(data["bottom"])

        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})

        cropped = _last_screenshot[top:bottom, left:right]
        if cropped.size == 0:
            return {"text": "", "results": []}

        from AutoScriptor.recognition.ocr_rec import ocr_manager
        engine = ocr_manager.get_ocr_engine()
        if engine is None:
            return {"text": "", "results": [], "error": "OCR 引擎未就绪"}
        result = engine.ocr(cropped, cls=True)
        text = ""
        results = []
        if result and result[0]:
            for item in result[0]:
                box_pts, (txt, conf) = item[0], item[1]
                results.append({"box": box_pts, "text": txt, "confidence": conf})
            text = result[0][0][1][0]
        return {"text": text, "results": results}
    except Exception as e:
        logger.error("editor/ocr error: %s\n%s", e, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/color ──

@router.post("/color")
async def editor_color(request: Request):
    global _last_screenshot
    try:
        data = await request.json()
        left, top, width, height = int(data["left"]), int(data["top"]), int(data["width"]), int(data["height"])

        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})

        from AutoScriptor.recognition.rec import get_box_color
        from AutoScriptor.utils.box import Box
        color = get_box_color(_last_screenshot, Box(left, top, width, height)) or ""
        return {"color": color}
    except Exception as e:
        logger.error("editor/color error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/locate ──

@router.post("/locate")
async def editor_locate(request: Request):
    """用多 scale OCR 校验当前 T 目标，分别返回 0.5/0.75/1.0 的匹配结果。"""
    global _last_screenshot
    try:
        data = await request.json()
        text = data.get("text", "").strip()
        left, top = int(data["left"]), int(data["top"])
        width, height = int(data["width"]), int(data["height"])
        color = data.get("color") or None

        ctx = _get_runtime()
        if ctx.mixctrl is None:
            return JSONResponse(status_code=503, content={"error": "mixctrl 未初始化"})

        empty_scales = {str(s): {"found": False, "boxes": []} for s in _LOCATE_SCALES}
        if not text:
            return {"found": False, "boxes": [], "scale_results": empty_scales}

        from AutoScriptor.utils.box import Box
        tgt_box = Box(left, top, width, height).margin()

        screenshot = _last_screenshot
        if screenshot is None:
            screenshot = ctx.mixctrl.screenshot()
            _last_screenshot = screenshot

        scale_results = {}
        all_boxes = []
        for scale in _LOCATE_SCALES:
            boxes = _locate_text_at_scale(screenshot, text, tgt_box, color, scale)
            scale_results[str(scale)] = {
                "found": bool(boxes),
                "boxes": [{"left": b.left, "top": b.top, "width": b.width, "height": b.height} for b in boxes],
            }
            all_boxes.extend(boxes)

        deduped = Box.merge_overlapping_boxes(all_boxes) if all_boxes else []
        box_dicts = [{"left": b.left, "top": b.top, "width": b.width, "height": b.height} for b in deduped]
        any_found = any(r["found"] for r in scale_results.values())
        return {"found": any_found, "boxes": box_dicts, "scale_results": scale_results}
    except Exception as e:
        logger.error("editor/locate error: %s\n%s", e, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/optimize-rect ──

@router.post("/optimize-rect")
async def editor_optimize_rect(request: Request):
    """基于色差阈值优化选区边缘。"""
    global _last_screenshot
    try:
        data = await request.json()
        left, top = int(data["left"]), int(data["top"])
        right, bottom = int(data["right"]), int(data["bottom"])
        threshold = int(data.get("threshold", 100))

        if _last_screenshot is None:
            return {"left": left, "top": top, "right": right, "bottom": bottom}

        if not (right > left and bottom > top):
            return {"left": left, "top": top, "right": right, "bottom": bottom}

        rgb = cv2.cvtColor(_last_screenshot, cv2.COLOR_BGR2RGB)
        cropped = rgb[top:bottom, left:right]
        arr = cropped.astype(np.int16)
        h, w, _ = arr.shape

        dx = np.max(np.abs(arr[:, 1:, :] - arr[:, :-1, :]), axis=2)
        dy = np.max(np.abs(arr[1:, :, :] - arr[:-1, :, :]), axis=2)

        mask = np.zeros((h, w), dtype=bool)
        mask[:, 1:][dx > threshold] = True
        mask[:, :-1][dx > threshold] = True
        mask[1:, :][dy > threshold] = True
        mask[:-1, :][dy > threshold] = True

        ys, xs = np.where(mask)
        if ys.size == 0:
            return {"left": left, "top": top, "right": right, "bottom": bottom}

        nl = int(left + xs.min())
        nt = int(top + ys.min())
        nr = int(left + xs.max() + 1)
        nb = int(top + ys.max() + 1)

        if nr <= nl or nb <= nt:
            return {"left": left, "top": top, "right": right, "bottom": bottom}

        return {"left": nl, "top": nt, "right": nr, "bottom": nb}
    except Exception as e:
        logger.error("editor/optimize-rect error: %s", e)
        return {"left": left, "top": top, "right": right, "bottom": bottom}


# ── POST /api/editor/save ──

@router.post("/save")
async def editor_save(request: Request):
    """保存选区图片到 assets/pic 并追加记录到 ui_map.csv。"""
    global _last_screenshot
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "名称不能为空"})

        left, top = int(data["left"]), int(data["top"])
        width, height = int(data["width"]), int(data["height"])
        free_x = bool(data.get("free_x", False))
        free_y = bool(data.get("free_y", False))
        only_ocr = bool(data.get("only_ocr", False))

        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})

        from AutoScriptor.utils.constant import cfg
        from pypinyin import lazy_pinyin
        import pandas as pd

        right, bottom = left + width, top + height
        cropped = _last_screenshot[top:bottom, left:right]

        save_left, save_top, save_w, save_h = left, top, width, height
        if free_x:
            save_left, save_w = 0, 1280
        if free_y:
            save_top, save_h = 0, 720

        pic_dir = os.path.join(os.getcwd(), cfg["app"]["name"], "assets", "pic")
        os.makedirs(pic_dir, exist_ok=True)

        fn = ""
        if not only_ocr:
            pinyin_name = "".join(lazy_pinyin(name))
            fn = f"{pinyin_name}@{save_left}#{save_top}#{save_w}#{save_h}.png"
            sp = os.path.join(pic_dir, fn)
            cv2.imwrite(sp, cropped)

        text = name
        if "-" in name:
            text = name.split("-")[-1]

        l2 = max(0, save_left - 10)
        t2 = max(0, save_top - 10)
        w2 = save_w + 20 if l2 + save_w + 20 <= 1280 else 1280 - l2
        h2 = save_h + 20 if t2 + save_h + 20 <= 720 else 720 - t2

        csv_path = os.path.join(os.getcwd(), cfg["app"]["name"], "assets", "config", "ui_map.csv")
        try:
            df = pd.read_csv(csv_path, header=None, encoding="utf-8")
        except FileNotFoundError:
            df = pd.DataFrame(columns=range(7))

        df.loc[len(df)] = [name, text, l2, t2, w2, h2, fn]
        df.to_csv(csv_path, index=False, header=False, encoding="utf-8")

        return {"ok": True, "message": f"已保存: {fn if fn else '仅保存配置'}"}
    except Exception as e:
        logger.error("editor/save error: %s\n%s", e, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})
