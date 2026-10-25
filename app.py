"""P&ID 图纸分析工具 — FastAPI 后端。"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from analyzer import ai_analyzer, exporter, local_analyzer
from analyzer.pdf_utils import load_as_images, normalize_for_ai, preview_b64

BASE_DIR = Path(__file__).resolve().parent
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}

# 运行模式：both=双引擎可切换 / local=仅本地智能识别(免API) / ai=仅AI视觉大模型(需API)
PID_MODE = os.environ.get("PID_MODE", "both").strip().lower()
if PID_MODE not in {"both", "local", "ai"}:
    PID_MODE = "both"

app = FastAPI(title="P&ID 图纸分析工具")

# 后台分析任务表：task_id -> {status, ts, result, error}
_tasks: dict[str, dict] = {}
_TASK_TTL = 1800  # 30 分钟后清理


@app.get("/")
def index() -> HTMLResponse:
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("__PID_MODE__", PID_MODE)
    return HTMLResponse(html)


def _merge_local(results: list[dict]) -> dict:
    """合并多页本地分析结果。"""
    merged: dict = {"equipment": [], "instruments": [], "pipelines": [],
                    "findings": [], "raw_text": ""}
    seen = {k: set() for k in ("equipment", "instruments", "pipelines")}
    for r in results:
        for key in ("equipment", "instruments", "pipelines"):
            for item in r.get(key, []):
                if item["tag"] not in seen[key]:
                    seen[key].add(item["tag"])
                    merged[key].append(item)
        merged["findings"].extend(r.get("findings", []))
        merged["raw_text"] += (r.get("raw_text", "") + "\n")
    return merged


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    engine: str = Form("auto"),
    api_key: str = Form(""),
    base_url: str = Form(""),
    model: str = Form(""),
) -> JSONResponse:
    """接收图纸并立即返回任务 ID，分析在后台线程执行，避免长请求被网关超时。"""
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的文件类型：{ext}，仅支持图片或 PDF")

    data = await file.read()
    if not data:
        raise HTTPException(400, "上传文件为空")

    task_id = uuid.uuid4().hex
    _tasks[task_id] = {"status": "running", "ts": time.time(), "result": None, "error": None}
    threading.Thread(
        target=_run_analysis,
        args=(task_id, data, filename, engine, api_key.strip(), base_url.strip(), model.strip()),
        daemon=True,
    ).start()
    return JSONResponse({"task_id": task_id})


def _run_analysis(
    task_id: str,
    data: bytes,
    filename: str,
    engine: str,
    api_key: str,
    base_url: str,
    model: str,
) -> None:
    """后台执行分析，结果写入任务表。"""
    try:
        images = load_as_images(data, filename)
        if not images:
            raise ValueError("未能从文件中提取图像")

        use_ai = engine == "ai" or (engine == "auto" and bool(api_key))
        meta = {
            "filename": filename,
            "engine": "ai" if use_ai else "local",
            "model": model if use_ai else "RapidOCR 深度学习 + CV 图元检测",
            "pages": len(images),
            "dimensions": f"{images[0].width}×{images[0].height}",
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if use_ai:
            if not api_key:
                raise ValueError("已选择 AI 分析，但未提供 API Key")
            if not model:
                raise ValueError("已选择 AI 分析，但未填写模型名称")
            result = ai_analyzer.analyze(
                [normalize_for_ai(im) for im in images],
                api_key=api_key,
                model=model,
                base_url=(base_url or ai_analyzer.DEFAULT_BASE_URL),
            )
            result["raw_text"] = ""
        else:
            merged = _merge_local([local_analyzer.analyze(img) for img in images])
            result = merged
            result["summary"] = (
                f"本地智能分析完成：共识别 {len(merged['equipment'])} 台设备、"
                f"{len(merged['instruments'])} 个仪表、{len(merged['pipelines'])} 条管线。"
            )
            result["flow"] = "（本地引擎不推断工艺物料流向；如需流向分析可选用 AI 视觉大模型）"

        result["meta"] = meta
        result["preview"] = preview_b64(images[0])
        _tasks[task_id] = {"status": "done", "ts": time.time(), "result": result, "error": None}
    except Exception as e:
        _tasks[task_id] = {"status": "error", "ts": time.time(), "result": None, "error": str(e)}


def _cleanup_tasks() -> None:
    now = time.time()
    for tid in [t for t, v in _tasks.items() if now - v.get("ts", 0) > _TASK_TTL]:
        _tasks.pop(tid, None)


@app.get("/api/status/{task_id}")
def status(task_id: str) -> JSONResponse:
    """轮询分析任务状态。"""
    _cleanup_tasks()
    task = _tasks.get(task_id)
    if not task:
        return JSONResponse({"status": "not_found"})
    if task["status"] == "done":
        return JSONResponse({"status": "done", "result": task["result"]})
    if task["status"] == "error":
        return JSONResponse({"status": "error", "error": task["error"]})
    return JSONResponse({"status": "running"})


@app.post("/api/export")
async def export(result: dict) -> Response:
    """前端回传分析结果，生成 Excel。"""
    try:
        xlsx = exporter.export_to_excel(result)
    except Exception as e:
        raise HTTPException(500, f"导出失败：{e}") from e
    fname = "P&ID分析结果.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"PID_analysis.xlsx\"; "
                f"filename*=UTF-8''{quote(fname)}"
            )
        },
    )


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
