"""
Editor API routes – WebUI 版图片编辑器后端
==========================================
提供截图获取、OCR、颜色识别、locate 校验、选区优化、保存等能力，
与前端 EditorPanel.js 配合使用。
"""

from __future__ import annotations

import ast
import asyncio
import base64
import os
import traceback
import types

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.box import b2p
from AutoScriptor.utils.cancel import suppress_cancel_checks
from AutoScriptor.core.targets import B

router = APIRouter(prefix="/api/editor", tags=["editor"])

# 缓存最近一次截图的 BGR ndarray，供 OCR / color / locate 复用
_last_screenshot: np.ndarray | None = None
# 缓存最近一次选区裁剪的模板图（用于图像匹配 locate）
_last_template: np.ndarray | None = None

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


def _ignore_cancel() -> None:
    return None


def _ensure_editor_mixctrl(reason: str):
    """Acquire live device controls only for explicit editor device actions."""
    return _get_runtime().ensure_device_session(
        reason=f"editor/{reason}",
        cancel_check=_ignore_cancel,
    )[0]


def _device_session_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": f"设备会话初始化失败: {exc}"},
    )


def _device_action_failed(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": str(exc)})


class _EditorVirtualMixControl:
    """Minimal mixctrl used by virtual editor snippets with an imported frame."""

    mode = "editor-virtual"

    def __init__(self, screenshot):
        self._screenshot = screenshot
        self.virtual_clicks: list[dict] = []
        self.virtual_swipes: list[dict] = []

    def screenshot(self):
        return self._screenshot

    def locate(self, tgt_triples, confidence=0.8, screenshot=None):
        from AutoScriptor.recognition.rec import locate_on_screen

        sources, boxes, colors = zip(*tgt_triples)
        frame = self._screenshot if screenshot is None else screenshot
        return locate_on_screen(frame, sources, confidence, boxes, colors)

    def click(self, x, y):
        self.virtual_clicks.append({"x": int(x), "y": int(y)})
        return None

    def long_click(self, x, y, duration=1.0):
        self.virtual_clicks.append({"x": int(x), "y": int(y)})
        return None

    def swipe(self, x1, y1, x2, y2, duration_s=1):
        self.virtual_swipes.append({
            "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
        })
        return None

    def input_text(self, text):
        return None

    def key_event(self, key_code):
        return None


def _screenshot_to_base64(img_bgr: np.ndarray) -> str:
    _, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── GET /api/editor/screenshot ──

@router.get("/screenshot")
async def editor_screenshot():
    global _last_screenshot
    try:
        mixctrl = _ensure_editor_mixctrl("screenshot")
        img = mixctrl.screenshot()
        if img is None:
            return JSONResponse(status_code=500, content={"error": "截图返回空"})
        _last_screenshot = img
        h, w = img.shape[:2]
        return {"image": _screenshot_to_base64(img), "width": w, "height": h}
    except Exception as e:
        logger.error("editor/screenshot error: %s", e)
        return _device_session_error(e)


def _decode_image_bytes(raw: bytes) -> np.ndarray | None:
    """将 PNG/JPEG/WebP 等字节解码为 BGR ndarray；失败返回 None。"""
    if not raw:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


# ── POST /api/editor/ingest-image ──

@router.post("/ingest-image")
async def editor_ingest_image(request: Request):
    """从客户端上传的 base64 图片更新 _last_screenshot，供 OCR / 选区 / 保存等与实时截图一致。
    切换图片时清空模板缓存。不要求 mixctrl。"""
    global _last_screenshot, _last_template
    try:
        data = await request.json()
        b64 = (data.get("image") or "").strip()
        if not b64:
            return JSONResponse(status_code=400, content={"error": "缺少 image"})
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64, validate=False)
        img = _decode_image_bytes(raw)
        if img is None:
            return JSONResponse(status_code=400, content={"error": "无法解码图片（支持常见位图格式）"})
        _last_screenshot = img
        _last_template = None
        h, w = img.shape[:2]
        return {"image": _screenshot_to_base64(img), "width": w, "height": h}
    except Exception as e:
        logger.error("editor/ingest-image error: %s", e)
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

        empty_scales = {str(s): {"found": False, "boxes": []} for s in _LOCATE_SCALES}
        if not text:
            return {"found": False, "boxes": [], "scale_results": empty_scales}

        from AutoScriptor.utils.box import Box
        tgt_box = Box(left, top, width, height).margin()

        screenshot = _last_screenshot
        if screenshot is None:
            try:
                screenshot = _ensure_editor_mixctrl("locate").screenshot()
            except Exception as e:
                return _device_session_error(e)
            if screenshot is None:
                return JSONResponse(status_code=500, content={"error": "截图返回空"})
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


# ── POST /api/editor/store-template ──

@router.post("/store-template")
async def editor_store_template(request: Request):
    """从 _last_screenshot 裁剪选区并缓存为模板，用于后续图像匹配。无需前端传图。"""
    global _last_template
    try:
        data = await request.json()
        left, top, right, bottom = int(data["left"]), int(data["top"]), int(data["right"]), int(data["bottom"])
        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})
        cropped = _last_screenshot[top:bottom, left:right]
        if cropped.size == 0:
            return JSONResponse(status_code=400, content={"error": "选区为空"})
        _last_template = cropped.copy()
        return {"ok": True}
    except Exception as e:
        logger.error("editor/store-template error: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/locate-image ──

@router.post("/locate-image")
async def editor_locate_image(request: Request):
    """用缓存的模板图在截图的指定 box（含 margin）内做多尺度模板匹配，返回与 /locate 结构一致的结果。"""
    global _last_screenshot, _last_template
    try:
        data = await request.json()
        left, top = int(data["left"]), int(data["top"])
        width, height = int(data["width"]), int(data["height"])

        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})
        if _last_template is None:
            return JSONResponse(status_code=400, content={"error": "请先框选区域以生成模板"})

        from AutoScriptor.utils.box import Box
        from AutoScriptor.recognition.img_rec import _locateAll_opencv

        tgt_box = Box(left, top, width, height).margin()
        region = (tgt_box.left, tgt_box.top, tgt_box.width, tgt_box.height)
        screenshot = _last_screenshot
        template = _last_template

        scale_cfgs = {
            "0.5":  (0.4, 0.6),
            "0.75": (0.65, 0.85),
            "1.0":  (0.9, 1.1),
        }
        scale_results = {}
        all_boxes = []
        for label, (mn, mx) in scale_cfgs.items():
            boxes = _locateAll_opencv(template, screenshot, confidence=0.8,
                                     region=region, min_scale=mn, max_scale=mx)
            filtered = [b for b in boxes if b.is_in(tgt_box)]
            scale_results[label] = {
                "found": bool(filtered),
                "boxes": [{"left": b.left, "top": b.top, "width": b.width, "height": b.height} for b in filtered],
            }
            all_boxes.extend(filtered)

        deduped = Box.merge_overlapping_boxes(all_boxes) if all_boxes else []
        box_dicts = [{"left": b.left, "top": b.top, "width": b.width, "height": b.height} for b in deduped]
        any_found = any(r["found"] for r in scale_results.values())
        return {"found": any_found, "boxes": box_dicts, "scale_results": scale_results}
    except Exception as e:
        logger.error("editor/locate-image error: %s\n%s", e, traceback.format_exc())
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

        from AutoScriptor.utils.app_config import cfg
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


# ── POST /api/editor/remote/click ──

@router.post("/remote/click")
async def editor_remote_click(request: Request):
    """在模拟器中点击指定坐标。"""
    try:
        data = await request.json()
        x, y = int(data["x"]), int(data["y"])
        try:
            with suppress_cancel_checks():
                mixctrl = _ensure_editor_mixctrl("remote/click")
        except Exception as e:
            return _device_session_error(e)
        with suppress_cancel_checks():
            mixctrl.click(x, y)
        return {"ok": True}
    except Exception as e:
        logger.error("editor/remote/click error: %s", e)
        return _device_action_failed(e)


# ── POST /api/editor/remote/swipe ──

@router.post("/remote/swipe")
async def editor_remote_swipe(request: Request):
    """在模拟器中执行滑动，与 AutoScriptor.core.api.swipe 一致（b2p、boost、滑动后稳定等）。"""
    try:
        data = await request.json()
        x1, y1 = int(data["x1"]), int(data["y1"])
        x2, y2 = int(data["x2"]), int(data["y2"])
        duration_s = int(round(float(data.get("duration_s", 1))))
        # 直接走 mixctrl，避免 api.swipe 开头的 check_cancel_raise 在「已停止」后仍拦截遥控
        from AutoScriptor.core import api as core_api

        core_api._ensure_boosted()
        start_b = B(x1, y1, 1, 1).box
        end_b = B(x2, y2, 1, 1).box
        try:
            with suppress_cancel_checks():
                mixctrl = _ensure_editor_mixctrl("remote/swipe")
        except Exception as e:
            return _device_session_error(e)
        with suppress_cancel_checks():
            mixctrl.swipe(*b2p(start_b), *b2p(end_b), duration_s)
        await asyncio.sleep(duration_s)
        return {"ok": True}
    except Exception as e:
        logger.error("editor/remote/swipe error: %s", e)
        return _device_action_failed(e)


# ── POST /api/editor/execute-code ──

_MAX_SNIPPET_LEN = 16000


def _editor_snippet_lhs_name(last_stmt: ast.stmt) -> str | None:
    """从最后一条语句解析「赋值左侧」可展示的单变量名；无法解析则返回 None。"""
    if isinstance(last_stmt, ast.Assign):
        t = last_stmt.targets[-1]
        if isinstance(t, ast.Name):
            return t.id
        if isinstance(t, (ast.Tuple, ast.List)) and t.elts:
            last = t.elts[-1]
            if isinstance(last, ast.Name):
                return last.id
        return None
    if isinstance(last_stmt, ast.AnnAssign):
        if isinstance(last_stmt.target, ast.Name):
            return last_stmt.target.id
        return None
    if isinstance(last_stmt, ast.AugAssign):
        if isinstance(last_stmt.target, ast.Name):
            return last_stmt.target.id
        return None
    return None


def _run_editor_snippet(
    code: str,
    *,
    virtual_only: bool = False,
    virtual_mixctrl=None,
) -> dict:
    """在受限命名空间中执行用户代码，捕获所有异常，不向外抛出。

    返回值通过 JSON 的 ``result`` 字段给出，始终为 ``repr(值)`` 的字符串（含 ``None`` → ``\"None\"``）。
    多行代码时若最后一行是表达式（如 ``locate(...)``），会对其求值并返回，避免 ``exec`` 丢弃结果。
    若最后一行是赋值（``info = extract_info(...)``、``x += 1``、``x: int = 1`` 等），默认返回左侧变量在命名空间中的值。
    否则可在末尾写 ``__result__ = ...`` 指定要展示的值。

    ``virtual_only=True`` 时临时替换 ``mixctrl`` 的 click/long_click/swipe，不下发模拟器，
    并在成功响应中附带 ``virtual_clicks`` / ``virtual_swipes`` 供前端画布标注。
    """
    import contextlib
    import io
    import time as time_mod
    import traceback as tb_mod

    from AutoScriptor.core.targets import B, I, T, V
    from AutoScriptor.utils.box import Box

    from AutoScriptor.core import api as api_mod

    safe_builtins = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "range": range,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "enumerate": enumerate,
        "zip": zip,
        "list": list,
        "tuple": tuple,
        "dict": dict,
        "set": set,
        "True": True,
        "False": False,
        "None": None,
        "isinstance": isinstance,
        "type": type,
        "repr": repr,
        "print": print,
    }

    ns: dict = {
        "__builtins__": safe_builtins,
        "time": time_mod,
        "Box": Box,
        "B": B,
        "T": T,
        "I": I,
        "V": V,
        "click": api_mod.click,
        "swipe": api_mod.swipe,
        "input": api_mod.input,
        "locate": api_mod.locate,
        "ui_T": api_mod.ui_T,
        "ui_F": api_mod.ui_F,
        "wait_for_appear": api_mod.wait_for_appear,
        "wait_for_disappear": api_mod.wait_for_disappear,
        "extract_info": api_mod.extract_info,
        "sleep": getattr(api_mod, "sleep", time_mod.sleep),
    }

    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "代码为空"}
    if len(code) > _MAX_SNIPPET_LEN:
        return {"ok": False, "error": f"代码过长（上限 {_MAX_SNIPPET_LEN} 字符）"}

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"ok": False, "error": f"语法错误: {e}"}

    original_mixctrl = api_mod.mixctrl
    if virtual_mixctrl is not None:
        api_mod.mixctrl = virtual_mixctrl

    stdout_buf = io.StringIO()
    _MISSING = object()

    virtual_clicks: list[dict] = []
    virtual_swipes: list[dict] = []
    backup: dict | None = None
    patched_mc = None
    if virtual_only:
        mc = api_mod.mixctrl
        if mc is None:
            return {"ok": False, "error": "mixctrl 未初始化"}
        if virtual_mixctrl is None:
            def _v_click(self, x, y):
                virtual_clicks.append({"x": int(x), "y": int(y)})

            def _v_long_click(self, x, y, duration=1.0):
                virtual_clicks.append({"x": int(x), "y": int(y)})

            def _v_swipe(self, x1, y1, x2, y2, duration_s=1):
                virtual_swipes.append({
                    "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                })

            backup = {
                "click": mc.click,
                "long_click": mc.long_click,
                "swipe": mc.swipe,
                "screenshot": mc.screenshot,
            }
            patched_mc = mc

            def _v_screenshot(self):
                # 与编辑器画布一致：导入图片时 _last_screenshot 为当前图，避免 extract_info 等仍读实时模拟器
                if _last_screenshot is not None:
                    return _last_screenshot
                return backup["screenshot"](self)

            mc.click = types.MethodType(_v_click, mc)
            mc.long_click = types.MethodType(_v_long_click, mc)
            mc.swipe = types.MethodType(_v_swipe, mc)
            mc.screenshot = types.MethodType(_v_screenshot, mc)

    try:
        with suppress_cancel_checks():
            with contextlib.redirect_stdout(stdout_buf):
                body = tree.body
                if not body:
                    return {"ok": False, "error": "代码为空"}

                value = _MISSING
                if len(body) == 1 and isinstance(body[0], ast.Expr):
                    value = eval(compile(ast.Expression(body[0].value), "<editor>", "eval"), ns, ns)
                elif isinstance(body[-1], ast.Expr):
                    head = ast.Module(body[:-1], type_ignores=[])
                    exec(compile(head, "<editor>", "exec"), ns, ns)
                    value = eval(compile(ast.Expression(body[-1].value), "<editor>", "eval"), ns, ns)
                else:
                    exec(compile(tree, "<editor>", "exec"), ns, ns)
                    lhs = _editor_snippet_lhs_name(body[-1])
                    if lhs is not None and lhs in ns:
                        value = ns[lhs]
                    elif "__result__" in ns:
                        value = ns["__result__"]

                out = stdout_buf.getvalue().strip()
                payload: dict = {"ok": True, "stdout": out or None}
                if value is not _MISSING:
                    payload["result"] = repr(value)
                if virtual_only:
                    if virtual_mixctrl is not None:
                        virtual_clicks.extend(virtual_mixctrl.virtual_clicks)
                        virtual_swipes.extend(virtual_mixctrl.virtual_swipes)
                    payload["virtual_clicks"] = virtual_clicks
                    payload["virtual_swipes"] = virtual_swipes
                return payload
    except BaseException as e:
        logger.warning("editor/execute-code snippet error: %s\n%s", e, tb_mod.format_exc())
        return {
            "ok": False,
            "error": str(e),
            "traceback": tb_mod.format_exc(),
        }
    finally:
        if backup is not None and patched_mc is not None:
            patched_mc.click = backup["click"]
            patched_mc.long_click = backup["long_click"]
            patched_mc.swipe = backup["swipe"]
            patched_mc.screenshot = backup["screenshot"]
        if virtual_mixctrl is not None:
            api_mod.mixctrl = original_mixctrl


@router.post("/execute-code")
async def editor_execute_code(request: Request):
    """执行自定义 Python 片段（与脚本相同的 API 命名空间），永不抛未捕获异常。"""
    try:
        data = await request.json()
        code = data.get("code", "")
        virtual_only = bool(data.get("virtual_only", False))
        virtual_mixctrl = None
        if virtual_only and _last_screenshot is not None:
            virtual_mixctrl = _EditorVirtualMixControl(_last_screenshot)
        else:
            try:
                _ensure_editor_mixctrl("execute-code")
            except Exception as e:
                return {"ok": False, "error": f"设备会话初始化失败: {e}"}
        return _run_editor_snippet(code, virtual_only=virtual_only, virtual_mixctrl=virtual_mixctrl)
    except Exception as e:
        logger.error("editor/execute-code error: %s\n%s", e, traceback.format_exc())
        return {"ok": False, "error": str(e)}


# ── POST /api/editor/preview-extract ──

@router.post("/preview-extract")
async def editor_preview_extract(request: Request):
    """对当前选区执行 extract_info 预览（与录制区生成代码一致），仅用于提示，不崩溃。"""
    try:
        data = await request.json()
        left, top = int(data["left"]), int(data["top"])
        width, height = int(data["width"]), int(data["height"])
        from AutoScriptor.core.api import extract_info
        from AutoScriptor.core.targets import B

        def _pp(s):
            if isinstance(s, str):
                return s.strip()
            return s

        frame = _last_screenshot
        if frame is None:
            try:
                frame = _ensure_editor_mixctrl("preview-extract").screenshot()
            except Exception as e:
                return {"ok": False, "error": f"设备会话初始化失败: {e}"}
        with suppress_cancel_checks():
            info = extract_info(
                B(left, top, width, height),
                post_process=_pp,
                ensure_not_empty=True,
                screenshot_frame=frame,
            )
        return {"ok": True, "info": info}
    except Exception as e:
        logger.warning("editor/preview-extract: %s", e)
        return {"ok": False, "error": str(e)}
