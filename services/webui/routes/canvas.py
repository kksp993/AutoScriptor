"""
Canvas API routes -- 可视化画布后端
====================================
提供画布图的保存、加载、列表、删除，以及从画布 JSON 生成 Python 脚本并
写入 custom_task 目录的能力。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_custom_task_dir, get_data_root

router = APIRouter(prefix="/api/canvas", tags=["canvas"])

_CANVAS_DIR: Path | None = None


def _get_canvas_dir() -> Path:
    global _CANVAS_DIR
    if _CANVAS_DIR is None:
        _CANVAS_DIR = get_data_root() / "canvas_data"
        _CANVAS_DIR.mkdir(parents=True, exist_ok=True)
    return _CANVAS_DIR


def _sanitize_name(name: str) -> str:
    """Remove characters unsafe for filenames."""
    return re.sub(r'[\\/:*?"<>|]', '_', name.strip())[:80]


# ── Save ──

@router.post("/save")
async def save_canvas(request: Request):
    try:
        body = await request.json()
        name = _sanitize_name(body.get("name", ""))
        if not name:
            return JSONResponse({"error": "名称不能为空"}, status_code=400)

        graph = body.get("graph", {})
        code = body.get("code", "")

        canvas_dir = _get_canvas_dir()

        # Save graph JSON
        graph_path = canvas_dir / f"{name}.json"
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)

        # Save generated code to custom_task directory
        if code:
            custom_dir = get_custom_task_dir()
            custom_dir.mkdir(parents=True, exist_ok=True)
            code_path = custom_dir / f"canvas_{name}.py"
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)
            logger.info("Canvas script saved: %s -> %s", name, code_path)

        return {"ok": True, "message": f"画布「{name}」已保存"}
    except Exception as e:
        logger.error("save_canvas error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Load ──

@router.get("/load")
async def load_canvas(name: str = ""):
    try:
        name = _sanitize_name(name)
        if not name:
            return JSONResponse({"error": "名称不能为空"}, status_code=400)

        graph_path = _get_canvas_dir() / f"{name}.json"
        if not graph_path.exists():
            return JSONResponse({"error": f"画布「{name}」不存在"}, status_code=404)

        with open(graph_path, "r", encoding="utf-8") as f:
            graph = json.load(f)

        return {"ok": True, "name": name, "graph": graph}
    except Exception as e:
        logger.error("load_canvas error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# ── List ──

@router.get("/list")
async def list_canvases():
    try:
        canvas_dir = _get_canvas_dir()
        canvases = []
        for f in sorted(canvas_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = f.stat()
            canvases.append({
                "name": f.stem,
                "updated_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                "size": stat.st_size,
            })
        return {"ok": True, "canvases": canvases}
    except Exception as e:
        logger.error("list_canvases error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Delete ──

@router.post("/delete")
async def delete_canvas(request: Request):
    try:
        body = await request.json()
        name = _sanitize_name(body.get("name", ""))
        if not name:
            return JSONResponse({"error": "名称不能为空"}, status_code=400)

        graph_path = _get_canvas_dir() / f"{name}.json"
        if graph_path.exists():
            graph_path.unlink()

        # Also remove generated code
        code_path = get_custom_task_dir() / f"canvas_{name}.py"
        if code_path.exists():
            code_path.unlink()

        return {"ok": True, "message": f"画布「{name}」已删除"}
    except Exception as e:
        logger.error("delete_canvas error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Generate code (preview only, no file write) ──

@router.post("/preview")
async def preview_code(request: Request):
    """Accept a graph JSON and return generated Python code without saving."""
    try:
        body = await request.json()
        graph = body.get("graph", {})
        name = body.get("name", "preview")

        code = _generate_code_from_graph(graph, name)
        return {"ok": True, "code": code}
    except Exception as e:
        logger.error("preview_code error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


def _generate_code_from_graph(graph: dict, name: str = "preview") -> str:
    """Server-side code generation from Drawflow export JSON.

    This mirrors the frontend logic so that the saved .py file is always
    consistent, even if the frontend preview has minor drift.
    """
    module = (graph.get("drawflow", {}).get("Home", {}).get("data", {}))
    if not module:
        return "# Empty canvas\npass"

    nodes = {}
    incoming: dict[str, set] = {}
    for nid, node in module.items():
        nodes[nid] = node
        incoming[nid] = set()
    for nid, node in module.items():
        for out_key, out_val in (node.get("outputs") or {}).items():
            for conn in (out_val.get("connections") or []):
                target_id = str(conn.get("node", ""))
                if target_id in incoming:
                    incoming[target_id].add(nid)

    ordered = []
    visited: set[str] = set()
    queue = [nid for nid in nodes if not incoming[nid]]
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        ordered.append(nodes[nid])
        for out_key, out_val in (nodes[nid].get("outputs") or {}).items():
            for conn in (out_val.get("connections") or []):
                tid = str(conn.get("node", ""))
                if tid in incoming:
                    incoming[tid].discard(nid)
                    if not incoming[tid]:
                        queue.append(tid)
    for nid in nodes:
        if nid not in visited:
            ordered.append(nodes[nid])

    safe_name = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', name)
    fn_name = f"canvas_{safe_name}_{int(time.time())}"

    lines = [
        "from AutoScriptor import *",
        "from ZmxyOL.task.task_register import register_task",
        "",
        f'@register_task(path_cn="自定义任务/画布脚本/{name}")',
        f"def {fn_name}():",
    ]

    indent = "    "
    has_body = False
    for node in ordered:
        d = node.get("data", {})
        code = _node_to_code(d, indent)
        if not code:
            continue
        has_body = True
        lines.append(code)
        ntype = d.get("_type", "")
        if ntype in ("if_branch", "loop"):
            indent += "    "
        if ntype == "loop_end" and len(indent) > 4:
            indent = indent[4:]

    if not has_body:
        lines.append("    pass")

    return "\n".join(lines)


def _node_to_code(d: dict, indent: str) -> str:
    ntype = d.get("_type", "")
    if ntype in ("start", "end", "loop_end", "comment"):
        return ""
    if ntype == "click":
        parts = [d.get("target", 'T("确定")')]
        parts.append(f"timeout={d.get('timeout', 3)}")
        if d.get("if_exist"):
            parts.append("if_exist=True")
        r = d.get("repeat")
        if r is not None and r > 1:
            parts.append(f"repeat={r}")
        return f"{indent}click({', '.join(parts)})"
    if ntype == "swipe":
        dur = d.get("duration_s", 1)
        return f"{indent}swipe({d.get('start_target', 'B(640,500,1,1)')}, {d.get('end_target', 'B(640,200,1,1)')}, duration_s={dur})"
    if ntype == "sleep":
        return f"{indent}sleep({d.get('seconds', 1)})"
    if ntype == "input_text":
        text = str(d.get("text", "")).replace('"', '\\"')
        field = d.get("target_field", "")
        field_part = f", {field}" if field else ""
        return f'{indent}input("{text}"{field_part})'
    if ntype == "key_event":
        return f"{indent}key_event({d.get('key_code', 4)})"
    if ntype == "locate":
        t = d.get("timeout", 0)
        t_part = f", timeout={t}" if t else ""
        tgt = d.get("target", 'T("确定")')
        return f"{indent}locate({tgt}{t_part})"
    if ntype == "wait_for_appear":
        t = d.get("timeout", 30)
        t_part = f", timeout={t}" if t != 30 else ""
        tgt = d.get("target", 'T("确定")')
        return f"{indent}wait_for_appear({tgt}{t_part})"
    if ntype == "wait_for_disappear":
        t = d.get("timeout", 30)
        t_part = f", timeout={t}" if t != 30 else ""
        tgt = d.get("target", 'T("确定")')
        return f"{indent}wait_for_disappear({tgt}{t_part})"
    if ntype == "extract_info":
        pp = d.get("post_process", "lambda s: s.strip()")
        ene = "True" if d.get("ensure_not_empty", True) else "False"
        digit_only = "True" if d.get("digit_only", False) else "False"
        return f"{indent}info = extract_info({d.get('target', 'B(0,0,1280,720)')}, post_process={pp}, ensure_not_empty={ene}, digit_only={digit_only})"
    if ntype == "ensure_in":
        scene = str(d.get("scene", "主界面")).replace('"', '\\"')
        return f'{indent}ensure_in("{scene}")'
    if ntype == "switch_base":
        base = str(d.get("base", "")).replace('"', '\\"')
        return f'{indent}switch_base("{base}")'
    if ntype == "if_branch":
        default_cond = 'ui_T(T("确定"))'
        return f"{indent}if {d.get('condition', default_cond)}:"
    if ntype == "loop":
        return f"{indent}for _i in range({d.get('times', 3)}):"
    if ntype == "set_var":
        vn = d.get("var_name", "result")
        expr = d.get("expression", "None")
        return f"{indent}{vn} = {expr}"
    return ""
