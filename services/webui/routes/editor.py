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
import csv
import builtins
import json
import keyword
import os
import textwrap
import traceback
import types
from threading import Lock
from typing import Callable

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.box import b2p
from AutoScriptor.utils.cancel import TaskCancelled, check_cancel_raise, suppress_cancel_checks
from AutoScriptor.core.targets import B
from services.webui.api_response import api_error, api_ok

router = APIRouter(prefix="/api/editor", tags=["editor"])

# 缓存最近一次截图的 BGR ndarray，供 OCR / color / locate 复用
_last_screenshot: np.ndarray | None = None
# 缓存最近一次选区裁剪的模板图（用于图像匹配 locate）
_last_template: np.ndarray | None = None

_LOCATE_SCALES = [0.5, 0.75, 1.0]
_UI_MAP_COLUMNS = ["key", "text", "left", "top", "width", "height", "img"]
_EDITOR_IMPORT_ALLOWLIST = (
    "AutoScriptor",
    "ZmxyOL",
    "math",
    "re",
    "json",
    "collections",
    "itertools",
    "functools",
)


def _editor_import_allowed(name: str) -> bool:
    root = (name or "").split(".", 1)[0]
    return any(root == item or name.startswith(item + ".") for item in _EDITOR_IMPORT_ALLOWLIST)


def _editor_safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or not _editor_import_allowed(name):
        raise ImportError(f"editor custom code import is not allowed: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


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


_editor_exec_lock = Lock()
_editor_exec_running = False
_editor_exec_stopping = False
_editor_request_cancel: Callable[[], None] | None = None
_editor_reset_cancel: Callable[[], None] | None = None
_editor_runtime_busy: Callable[[], bool] | None = None
_editor_reload_custom_tasks: Callable[[], int] | None = None


def configure_editor_execution_controls(
    *,
    request_cancel: Callable[[], None],
    reset_cancel: Callable[[], None],
    runtime_busy: Callable[[], bool],
) -> None:
    """Register runtime cancellation hooks without importing server.py here."""
    global _editor_request_cancel, _editor_reset_cancel, _editor_runtime_busy
    _editor_request_cancel = request_cancel
    _editor_reset_cancel = reset_cancel
    _editor_runtime_busy = runtime_busy


def configure_editor_custom_task_save_controls(
    *,
    reload_custom_tasks: Callable[[], int] | None = None,
) -> None:
    """Register optional lifecycle hooks for editor-saved custom task scripts."""
    global _editor_reload_custom_tasks
    _editor_reload_custom_tasks = reload_custom_tasks


def _begin_editor_execution() -> JSONResponse | None:
    if _editor_runtime_busy is not None and _editor_runtime_busy():
        return api_error(
            409,
            "当前已有任务在运行，请先终止当前任务后再执行编辑器代码",
            code="runtime_busy",
        )
    with _editor_exec_lock:
        global _editor_exec_running, _editor_exec_stopping
        if _editor_exec_running:
            return api_error(
                409,
                "编辑器自定义代码正在执行，请先终止或等待完成",
                code="editor_execution_busy",
            )
        _editor_exec_running = True
        _editor_exec_stopping = False
    if _editor_reset_cancel is not None:
        _editor_reset_cancel()
    return None


def _end_editor_execution() -> None:
    with _editor_exec_lock:
        global _editor_exec_running, _editor_exec_stopping
        was_stopping = _editor_exec_stopping
        _editor_exec_running = False
        _editor_exec_stopping = False
    if was_stopping and _editor_reset_cancel is not None:
        _editor_reset_cancel()


def _request_editor_execution_stop() -> dict:
    with _editor_exec_lock:
        global _editor_exec_stopping
        if not _editor_exec_running:
            return api_ok(
                status="idle",
                running=False,
                stopping=False,
                message="当前没有编辑器代码在执行",
            )
        _editor_exec_stopping = True
    if _editor_request_cancel is not None:
        _editor_request_cancel()
    return api_ok(
        status="stopping",
        running=True,
        stopping=True,
        message="已发送终止执行请求",
    )


def _ignore_cancel() -> None:
    return None


def _ensure_editor_mixctrl(reason: str, *, cancel_check: Callable[[], None] | None = _ignore_cancel):
    """Acquire live device controls only for explicit editor device actions."""
    return _get_runtime().ensure_device_session(
        reason=f"editor/{reason}",
        cancel_check=cancel_check,
        launch_app=False,
    )[0]


def _require_editor_device_unlock(request: Request) -> JSONResponse | None:
    """Require account unlock for editor actions that can operate the device."""
    if not cfg.has_decrypted_credentials():
        return JSONResponse(
            status_code=403,
            content={
                "error": "请先验证账号安全密码后再使用编辑器设备控制",
                "code": "credential_locked",
                "need_credential_unlock": True,
            },
        )
    return None


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


def _clamp_crop_rect(left: int, top: int, width: int, height: int, frame: np.ndarray) -> tuple[int, int, int, int]:
    frame_h, frame_w = frame.shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError("选区宽高必须大于 0")
    right = left + width
    bottom = top + height
    if left < 0 or top < 0 or right > frame_w or bottom > frame_h:
        raise ValueError(f"选区超出截图范围: ({left}, {top}, {width}, {height}) / {frame_w}x{frame_h}")
    return left, top, right, bottom


def _is_fullscreen_like_rect(left: int, top: int, right: int, bottom: int, frame: np.ndarray) -> bool:
    """Protect image matching from accidental full-frame templates."""
    frame_h, frame_w = frame.shape[:2]
    rect_w = right - left
    rect_h = bottom - top
    if left == 0 and top == 0 and rect_w == frame_w and rect_h == frame_h:
        return True
    frame_area = frame_w * frame_h
    return frame_area > 0 and (rect_w * rect_h / frame_area) >= 0.85


def _unique_filename(directory: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    candidate = filename
    idx = 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem}__{idx}{ext}"
        idx += 1
    return candidate


def _safe_asset_stem(raw: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw).strip("_")
    return stem or "template"


def _safe_custom_task_stem(raw: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw).strip("_")
    stem = stem[:80].strip("_") or "editor_custom_task"
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if stem.upper() in reserved:
        stem = f"{stem}_script"
    return stem


def _safe_custom_task_title(raw: str, fallback: str) -> str:
    title = "".join(ch if ch not in "\r\n\t\\/:*?\"<>|" else "_" for ch in raw).strip(" _")
    return title[:80].strip(" _") or fallback


def _normalize_editor_custom_task_filename(raw: str) -> str:
    name = str(raw or "").replace("\\", "/").split("/")[-1].strip()
    if name.lower().endswith(".py"):
        name = name[:-3]
    return f"{_safe_custom_task_stem(name)}.py"


def _normalize_editor_task_path(raw: str | None, fallback: str) -> str:
    value = str(fallback if raw is None else raw).replace("\\", "/").strip()
    if not value:
        raise ValueError("脚本名称不能为空")
    parts = []
    for part in value.split("/"):
        cleaned = _safe_custom_task_title(part, "")
        if cleaned:
            parts.append(cleaned)
    if not parts:
        raise ValueError("脚本名称不能为空")
    if parts[0] != "自定义任务":
        parts.insert(0, "自定义任务")
    if len(parts) < 2:
        raise ValueError("脚本名称必须包含自定义任务下的具体路径")
    return "/".join(parts)


_EDITOR_PARAM_TYPE_ALIASES = {
    "str": "str",
    "string": "str",
    "文本": "str",
    "字符串": "str",
    "int": "int",
    "integer": "int",
    "整数": "int",
    "float": "float",
    "number": "float",
    "数字": "float",
    "浮点": "float",
    "bool": "bool",
    "boolean": "bool",
    "布尔": "bool",
    "enum": "enum",
    "enum_single": "enum",
    "enum-single": "enum",
    "enum(单选)": "enum",
    "单选": "enum",
    "枚举": "enum",
    "enum_multi": "enum_multi",
    "enum_multiple": "enum_multi",
    "enum-multiple": "enum_multi",
    "enum(多选)": "enum_multi",
    "多选": "enum_multi",
    "枚举多选": "enum_multi",
}


def _normalize_editor_param_type(raw: object) -> str:
    key = str(raw or "str").strip()
    normalized = _EDITOR_PARAM_TYPE_ALIASES.get(key.lower()) or _EDITOR_PARAM_TYPE_ALIASES.get(key)
    if not normalized:
        raise ValueError(f"不支持的字段类型: {key}")
    return normalized


def _normalize_editor_enum_options(raw: object, field_name: str) -> list[str]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError(f"Enum 参数 {field_name} 必须填写选项")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Enum 参数 {field_name} 的选项必须是 JSON 字符串数组") from e
    elif isinstance(raw, (list, tuple)):
        parsed = raw
    else:
        raise ValueError(f"Enum 参数 {field_name} 的选项必须是数组")

    if not isinstance(parsed, (list, tuple)):
        raise ValueError(f"Enum 参数 {field_name} 的选项必须是数组")
    seen = set()
    options: list[str] = []
    for item in parsed:
        option = str(item).strip()
        if not option:
            raise ValueError(f"Enum 参数 {field_name} 包含空选项")
        if option in seen:
            continue
        seen.add(option)
        options.append(option)
    if not options:
        raise ValueError(f"Enum 参数 {field_name} 必须至少包含一个选项")
    return options


def _normalize_editor_param_specs(raw_params: object) -> list[dict[str, object]]:
    if raw_params in (None, "", []):
        return []
    if not isinstance(raw_params, list):
        raise ValueError("参数设置必须是列表")

    specs: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for idx, item in enumerate(raw_params, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx} 个参数设置无效")
        raw_name = str(item.get("name") or item.get("field_name") or item.get("fieldName") or item.get("field") or "").strip()
        raw_type = item.get("type") or item.get("field_type") or item.get("fieldType") or "str"
        description = str(item.get("description") or item.get("desc") or item.get("explanation") or "").strip()
        enum_options = item.get("enum_options", item.get("enumOptions", item.get("options")))
        if not raw_name and not description and enum_options in (None, "", []):
            continue
        if not raw_name:
            raise ValueError(f"第 {idx} 个参数缺少字段名称")
        if not raw_name.isidentifier() or keyword.iskeyword(raw_name):
            raise ValueError(f"字段名称必须是合法 Python 参数名: {raw_name}")
        if raw_name in seen_names:
            raise ValueError(f"字段名称重复: {raw_name}")
        seen_names.add(raw_name)

        param_type = _normalize_editor_param_type(raw_type)
        spec: dict[str, object] = {
            "name": raw_name,
            "type": param_type,
            "description": description,
        }
        if param_type in {"enum", "enum_multi"}:
            spec["enum_options"] = _normalize_editor_enum_options(enum_options, raw_name)
        specs.append(spec)
    return specs


def _editor_task_doc_with_param_descriptions(task_doc: str, params: list[dict[str, object]]) -> str:
    doc = str(task_doc or "").strip()
    param_lines = [
        f"- {param['name']}: {param['description']}"
        for param in params
        if str(param.get("description") or "").strip()
    ]
    if not param_lines:
        return doc
    param_doc = "参数说明:\n" + "\n".join(param_lines)
    return f"{doc}\n\n{param_doc}" if doc else param_doc


def _decorator_ref_is_register_task(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "register_task"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "register_task"
    return False


def _register_task_decorator_info(tree: ast.AST) -> tuple[bool, bool]:
    has_register_task = False
    missing_path_cn = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if not _decorator_ref_is_register_task(decorator.func):
                    continue
                has_register_task = True
                if not any(keyword.arg == "path_cn" for keyword in decorator.keywords):
                    missing_path_cn = True
            elif _decorator_ref_is_register_task(decorator):
                has_register_task = True
                missing_path_cn = True
    return has_register_task, missing_path_cn


def _editor_enum_class_source(class_name: str, enum_options: list[str]) -> str:
    lines = [f"class {class_name}(str, enum.Enum):"]
    for idx, option in enumerate(enum_options, start=1):
        lines.append(f"    OPTION_{idx} = {option!r}")
    return "\n".join(lines)


def _editor_task_signature(params: list[dict[str, object]]) -> tuple[str, list[str]]:
    if not params:
        return "def task():\n", []

    enum_sources: list[str] = []
    signature_args: list[str] = []
    enum_index = 0
    for param in params:
        name = str(param["name"])
        param_type = str(param["type"])
        if param_type == "enum":
            enum_index += 1
            class_name = f"EditorParam{enum_index}Enum"
            enum_sources.append(_editor_enum_class_source(class_name, list(param["enum_options"])))
            signature_args.append(f"{name}: {class_name} = {class_name}.OPTION_1")
        elif param_type == "enum_multi":
            enum_index += 1
            class_name = f"EditorParam{enum_index}Enum"
            enum_sources.append(_editor_enum_class_source(class_name, list(param["enum_options"])))
            signature_args.append(f"{name}: list = [{class_name}.OPTION_1]")
        elif param_type == "int":
            signature_args.append(f"{name}: int = 0")
        elif param_type == "float":
            signature_args.append(f"{name}: float = 0.0")
        elif param_type == "bool":
            signature_args.append(f"{name}: bool = False")
        else:
            signature_args.append(f"{name}: str = ''")

    signature = "def task(\n" + "".join(f"    {arg},\n" for arg in signature_args) + "):\n"
    return signature, enum_sources


def _build_wrapped_custom_task_source(name: str, code: str, metadata: dict | None = None) -> tuple[str, str]:
    clean_name = str(name or "").replace("\\", "/").split("/")[-1].strip()
    if clean_name.lower().endswith(".py"):
        clean_name = clean_name[:-3]
    stem = _safe_custom_task_stem(clean_name)
    title = _safe_custom_task_title(clean_name, stem)

    metadata = metadata if isinstance(metadata, dict) else {}
    raw_task_path = metadata.get("task_path") if "task_path" in metadata else None
    task_path = _normalize_editor_task_path(raw_task_path, f"自定义任务/编辑器保存/{title}")
    description = str(metadata.get("description") or "").strip() or "从编辑器保存的自定义脚本"
    task_doc = str(metadata.get("task_doc") or metadata.get("task_docs") or "").strip()
    params = _normalize_editor_param_specs(metadata.get("params"))
    final_task_doc = _editor_task_doc_with_param_descriptions(task_doc, params)
    register_kwargs = dict(path_cn=task_path, description=description, task_doc=final_task_doc)

    signature, enum_sources = _editor_task_signature(params)
    body = textwrap.indent(code.rstrip() or "pass", "    ")
    imports = [
        "from AutoScriptor import *",
        "from ZmxyOL.nav.api import *",
        "from ZmxyOL.nav.envs.decorators import *",
        "from ZmxyOL.task.task_register import register_task",
    ]
    if enum_sources:
        imports.insert(0, "import enum")
    decorator = (
        "@register_task(\n"
        f"    path_cn={register_kwargs['path_cn']!r},\n"
        f"    description={register_kwargs['description']!r},\n"
        f"    task_doc={register_kwargs['task_doc']!r},\n"
        ")"
    )
    sections = ["\n".join(imports), *enum_sources, f"{decorator}\n{signature}{body}"]
    return "\n\n".join(sections).rstrip() + "\n", task_path


def _prepare_editor_custom_task_source(name: str, code: str, metadata: dict | None = None) -> tuple[str, bool, str | None]:
    code = (code or "").strip()
    if not code:
        raise ValueError("代码为空")
    if len(code) > _MAX_SNIPPET_LEN:
        raise ValueError(f"代码过长（上限 {_MAX_SNIPPET_LEN} 字符）")
    tree = ast.parse(code)
    has_register_task, missing_path_cn = _register_task_decorator_info(tree)
    if has_register_task:
        if missing_path_cn:
            raise ValueError('data/custom_task 下的 @register_task 必须显式传入 path_cn="自定义任务/..."')
        return code.rstrip() + "\n", False, None
    source, task_path = _build_wrapped_custom_task_source(name, code, metadata)
    ast.parse(source)
    return source, True, task_path


def _editor_script_write_busy() -> JSONResponse | None:
    if _editor_runtime_busy is not None and _editor_runtime_busy():
        return api_error(
            409,
            "当前已有任务在运行，请先终止当前任务后再保存脚本",
            code="runtime_busy",
        )
    with _editor_exec_lock:
        if _editor_exec_running:
            return api_error(
                409,
                "编辑器自定义代码正在执行，请先终止或等待完成后再保存脚本",
                code="editor_execution_busy",
            )
    return None


def _public_module_symbols(module) -> dict:
    names = getattr(module, "__all__", None) or [name for name in dir(module) if not name.startswith("_")]
    return {name: getattr(module, name) for name in names if not name.startswith("_")}


def _editor_nav_namespace() -> dict:
    from ZmxyOL.nav import api as nav_api
    from ZmxyOL.nav.envs import decorators as nav_decorators

    symbols = {}
    symbols.update(_public_module_symbols(nav_decorators))
    symbols.update(_public_module_symbols(nav_api))
    symbols["ensure_in"] = nav_api.ensure_in
    symbols["LOC_ENV"] = nav_decorators.LOC_ENV
    return symbols


def _read_ui_map_rows(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path):
        return []
    rows: list[dict] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "key" in reader.fieldnames:
            for row in reader:
                rows.append({col: row.get(col, "") for col in _UI_MAP_COLUMNS})
            return rows
        f.seek(0)
        for raw in csv.reader(f):
            if not raw:
                continue
            if raw[0] == "key":
                continue
            padded = (raw + [""] * len(_UI_MAP_COLUMNS))[: len(_UI_MAP_COLUMNS)]
            rows.append(dict(zip(_UI_MAP_COLUMNS, padded)))
    return rows


def _write_ui_map_rows(csv_path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    deduped: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        key = str(row.get("key", "")).strip()
        if not key:
            continue
        if key not in deduped:
            order.append(key)
        deduped[key] = {col: row.get(col, "") for col in _UI_MAP_COLUMNS}
        deduped[key]["key"] = key
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_UI_MAP_COLUMNS)
        writer.writeheader()
        for key in order:
            writer.writerow(deduped[key])


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
        template_left = int(data.get("template_left", left))
        template_top = int(data.get("template_top", top))
        template_width = int(data.get("template_width", width))
        template_height = int(data.get("template_height", height))
        free_x = bool(data.get("free_x", False))
        free_y = bool(data.get("free_y", False))
        only_ocr = bool(data.get("only_ocr", False))
        allow_fullscreen_template = bool(data.get("allow_fullscreen_template", False))

        if _last_screenshot is None:
            return JSONResponse(status_code=400, content={"error": "请先获取截图"})

        from AutoScriptor.utils.app_config import cfg
        from pypinyin import lazy_pinyin

        left, top, right, bottom = _clamp_crop_rect(left, top, width, height, _last_screenshot)
        template_left, template_top, template_right, template_bottom = _clamp_crop_rect(
            template_left,
            template_top,
            template_width,
            template_height,
            _last_screenshot,
        )
        if (
            not only_ocr
            and not allow_fullscreen_template
            and _is_fullscreen_like_rect(template_left, template_top, template_right, template_bottom, _last_screenshot)
        ):
            return JSONResponse(
                status_code=400,
                content={
                    "error": "模板裁剪框接近整张截图。若想全屏检索，请只打开自由 X/Y；模板本身应框住目标小图。"
                },
            )
        cropped = _last_screenshot[template_top:template_bottom, template_left:template_right]

        save_left, save_top, save_w, save_h = left, top, right - left, bottom - top
        frame_h, frame_w = _last_screenshot.shape[:2]
        if free_x:
            save_left, save_w = 0, frame_w
        if free_y:
            save_top, save_h = 0, frame_h

        from AutoScriptor.utils.paths import get_assets_dir

        assets_root = get_assets_dir()
        pic_dir = str(assets_root / "pic")
        os.makedirs(pic_dir, exist_ok=True)
        csv_path = str(assets_root / "config" / "ui_map.csv")
        rows = _read_ui_map_rows(csv_path)
        existing = next((row for row in rows if row.get("key") == name), None)

        fn = ""
        if not only_ocr:
            pinyin_name = _safe_asset_stem("".join(lazy_pinyin(name)))
            raw_fn = f"{pinyin_name}@{save_left}#{save_top}#{save_w}#{save_h}.png"
            fn = _unique_filename(pic_dir, raw_fn)
            sp = os.path.join(pic_dir, fn)
            if not cv2.imwrite(sp, cropped):
                raise RuntimeError(f"保存模板图片失败: {sp}")
        elif existing is not None:
            fn = ""

        text = name
        if "-" in name:
            text = name.split("-")[-1]

        l2 = max(0, save_left - 10)
        t2 = max(0, save_top - 10)
        w2 = save_w + 20 if l2 + save_w + 20 <= frame_w else frame_w - l2
        h2 = save_h + 20 if t2 + save_h + 20 <= frame_h else frame_h - t2

        new_row = {
            "key": name,
            "text": text,
            "left": int(l2),
            "top": int(t2),
            "width": int(w2),
            "height": int(h2),
            "img": fn,
        }
        action = "更新" if existing is not None else "新增"
        rows = [row for row in rows if row.get("key") != name]
        rows.append(new_row)
        _write_ui_map_rows(csv_path, rows)

        return {"ok": True, "message": f"已{action}: {fn if fn else '仅保存配置'}", "filename": fn, "action": action}
    except Exception as e:
        logger.error("editor/save error: %s\n%s", e, traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── POST /api/editor/remote/click ──

@router.post("/remote/click")
async def editor_remote_click(request: Request):
    """在模拟器中点击指定坐标。"""
    locked = _require_editor_device_unlock(request)
    if locked is not None:
        return locked
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
    locked = _require_editor_device_unlock(request)
    if locked is not None:
        return locked
    try:
        data = await request.json()
        x1, y1 = int(data["x1"]), int(data["y1"])
        x2, y2 = int(data["x2"]), int(data["y2"])
        duration_s = int(round(float(data.get("duration_s", 1))))
        # 直接走 mixctrl，避免 api.swipe 开头的 check_cancel_raise 在「已停止」后仍拦截遥控
        from AutoScriptor.core import api as core_api

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


def _validate_editor_snippet(code: str) -> dict:
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "代码为空"}
    if len(code) > _MAX_SNIPPET_LEN:
        return {"ok": False, "error": f"代码过长（上限 {_MAX_SNIPPET_LEN} 字符）"}
    try:
        tree = ast.parse(code)
        compile(tree, "<editor>", "exec")
    except SyntaxError as e:
        loc = f"第 {e.lineno} 行"
        if e.offset:
            loc += f" 第 {e.offset} 列"
        return {"ok": False, "error": f"语法错误（{loc}）: {e.msg}"}

    warnings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _editor_import_allowed(alias.name):
                    warnings.append(f"导入 {alias.name} 会被执行器拦截")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not _editor_import_allowed(module):
                warnings.append(f"导入 {module or '<relative>'} 会被执行器拦截")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sleep"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "time"
        ):
            warnings.append("建议使用 sleep(...)，不要使用 time.sleep(...)，这样停止按钮才能及时生效")

    # Keep repeated AST warnings readable in the toast.
    deduped = list(dict.fromkeys(warnings))[:6]
    return {"ok": True, "warnings": deduped}


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

    from AutoScriptor.core.targets import B, I, T
    from AutoScriptor.utils.box import Box
    from AutoScriptor.utils.box_grid import indexof, make_box_grid

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
        "Exception": Exception,
        "ValueError": ValueError,
        "RuntimeError": RuntimeError,
        "TypeError": TypeError,
        "__import__": _editor_safe_import,
    }

    ns: dict = {
        "__name__": "__editor__",
        "__builtins__": safe_builtins,
        "time": time_mod,
        "Box": Box,
        "make_box_grid": make_box_grid,
        "indexof": indexof,
        "B": B,
        "T": T,
        "I": I,
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
    ns.update(_editor_nav_namespace())

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
        with contextlib.nullcontext():
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
    except TaskCancelled as e:
        logger.info("editor/execute-code stopped: %s", e)
        return {
            "ok": False,
            "error": str(e),
            "code": "editor_execution_stopped",
        }
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


def _execute_editor_code_sync(code: str, virtual_only: bool) -> dict:
    try:
        virtual_mixctrl = None
        if virtual_only and _last_screenshot is not None:
            virtual_mixctrl = _EditorVirtualMixControl(_last_screenshot)
        else:
            _ensure_editor_mixctrl("execute-code", cancel_check=check_cancel_raise)
        return _run_editor_snippet(code, virtual_only=virtual_only, virtual_mixctrl=virtual_mixctrl)
    except TaskCancelled as e:
        logger.info("editor/execute-code stopped before snippet: %s", e)
        return {"ok": False, "error": str(e), "code": "editor_execution_stopped"}


@router.post("/validate-code")
async def editor_validate_code(request: Request):
    """校验自定义 Python 片段的语法，并提示执行器会拦截的明显问题。"""
    try:
        data = await request.json()
        return _validate_editor_snippet(data.get("code", ""))
    except Exception as e:
        logger.error("editor/validate-code error: %s\n%s", e, traceback.format_exc())
        return {"ok": False, "error": str(e)}


@router.post("/save-custom-task")
async def editor_save_custom_task(request: Request):
    """Save editor code as a UTF-8 custom task script under data/custom_task/."""
    busy = _editor_script_write_busy()
    if busy is not None:
        return busy
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return api_error(400, "无效的保存请求", code="invalid_payload")
        code = data.get("code", "")
        raw_filename = str(data.get("filename") or data.get("name") or "editor_custom_task.py")
        filename = _normalize_editor_custom_task_filename(raw_filename)
        raw_name = str(data.get("name") or os.path.splitext(filename)[0])
        source, wrapped, task_path = _prepare_editor_custom_task_source(raw_name, code, data)

        from AutoScriptor.utils.paths import get_custom_task_dir

        root = get_custom_task_dir()
        root.mkdir(parents=True, exist_ok=True)
        root_resolved = root.resolve()
        target_path = (root / filename).resolve()
        if target_path.parent != root_resolved:
            return api_error(400, "脚本文件名非法", code="invalid_filename")
        compile(source, str(target_path), "exec")

        tmp_path = target_path.with_name(f".{target_path.name}.tmp")
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(source)
        os.replace(tmp_path, target_path)

        config_version = None
        reloaded = False
        if _editor_reload_custom_tasks is not None:
            try:
                config_version = _editor_reload_custom_tasks()
                reloaded = True
            except Exception as e:
                logger.error("editor/save-custom-task reload error: %s\n%s", e, traceback.format_exc())
                return api_error(
                    500,
                    f"脚本已保存，但任务重载失败: {e}",
                    code="reload_custom_task_failed",
                    filename=target_path.name,
                    path=str(target_path),
                )

        message = "已保存脚本并重载任务" if reloaded else "已保存脚本，任务列表将在下次重载后更新"
        return api_ok(
            message=message,
            filename=target_path.name,
            path=str(target_path),
            wrapped=wrapped,
            task_path=task_path,
            reloaded=reloaded,
            config_version=config_version,
        )
    except SyntaxError as e:
        loc = f"第 {e.lineno} 行"
        if e.offset:
            loc += f" 第 {e.offset} 列"
        return api_error(400, f"语法错误（{loc}）: {e.msg}", code="syntax_error")
    except ValueError as e:
        return api_error(400, str(e), code="invalid_payload")
    except Exception as e:
        logger.error("editor/save-custom-task error: %s\n%s", e, traceback.format_exc())
        return api_error(500, str(e), code="save_custom_task_failed")


@router.post("/execute-code/stop")
async def editor_stop_execution():
    """Request cooperative cancellation for the current editor custom-code run."""
    return _request_editor_execution_stop()


@router.post("/execute-code")
async def editor_execute_code(request: Request):
    """执行自定义 Python 片段（与脚本相同的 API 命名空间），永不抛未捕获异常。"""
    busy = _begin_editor_execution()
    if busy is not None:
        return busy
    try:
        data = await request.json()
        code = data.get("code", "")
        virtual_only = bool(data.get("virtual_only", False))
        if not (virtual_only and _last_screenshot is not None):
            locked = _require_editor_device_unlock(request)
            if locked is not None:
                return locked
        return await asyncio.to_thread(_execute_editor_code_sync, code, virtual_only)
    except Exception as e:
        logger.error("editor/execute-code error: %s\n%s", e, traceback.format_exc())
        return {"ok": False, "error": str(e)}
    finally:
        _end_editor_execution()


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
