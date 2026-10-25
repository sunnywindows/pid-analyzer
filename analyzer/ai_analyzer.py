"""基于 OpenAI 兼容视觉大模型的 P&ID 分析器。

支持 GPT-4V / 通义千问 VL / 智谱 GLM-4V / Kimi-VL 等所有 OpenAI 兼容接口。
"""
from __future__ import annotations

import json
import re

import requests

from .pdf_utils import image_to_b64_png

DEFAULT_BASE_URL = "https://api.openai.com/v1"

SYSTEM_PROMPT = (
    "你是一名资深的化工/石化工艺设计工程师，精通 P&ID（管道及仪表流程图）图纸识读。"
    "你的任务是从给定的图纸图像中，尽可能完整、准确地提取结构化信息。"
)

USER_PROMPT = """请仔细识读这张 P&ID 图纸，并按以下 JSON 结构输出结果（务必是合法 JSON，不要输出任何其它文字）：

{
  "summary": "用2-3句话概括这张图纸的工艺内容和范围",
  "flow": "描述主要工艺物料流向（从哪个设备到哪个设备，物料的工艺路径）",
  "equipment": [{"tag": "设备位号，如 V-101", "type": "设备类型中文名，如 储罐/塔/泵/换热器/反应器/压缩机/过滤器/分离器", "description": "该设备的简要说明"}],
  "instruments": [{"tag": "仪表位号，如 PI-101 / FV-102", "type": "仪表类型中文名，如 压力指示/温度变送/流量调节阀/安全阀", "description": "安装位置或用途简要说明"}],
  "pipelines": [{"tag": "管线号，如 4\\\"-PG-1001", "from": "起点设备位号或来源", "to": "终点设备位号或去向", "spec": "管径/材质/介质等规格信息"}],
  "findings": ["值得注意的发现或存疑点，如缺失标注、可能存在设计问题等，没有则为空数组"]
}

要求：
1. 位号、管线号务必按图纸原文提取，不要编造；识别不清的项宁可不写。
2. equipment / instruments / pipelines / findings 均为数组，没有识别到则为空数组 []。
3. 只输出 JSON 本身，不要用 markdown 代码块包裹，不要输出解释性文字。"""


def _extract_json(text: str) -> dict:
    """从模型输出中健壮地提取 JSON 对象。"""
    text = text.strip()
    # 去掉 markdown 代码围栏
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # 取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型输出中未找到 JSON 对象")
    return json.loads(text[start : end + 1])


def _normalize(result: dict) -> dict:
    """规整模型输出为统一结构。"""
    def as_list(key: str) -> list[dict]:
        v = result.get(key, [])
        if not isinstance(v, list):
            return []
        out = []
        for item in v:
            if isinstance(item, dict):
                out.append(item)
        return out

    def clean_rows(rows: list[dict]) -> list[dict]:
        cleaned = []
        for r in rows:
            tag = str(r.get("tag", "") or "").strip()
            if not tag:
                continue
            cleaned.append({
                "tag": tag,
                "type": str(r.get("type", "") or "").strip(),
                "description": str(r.get("description", "") or "").strip(),
                "confidence": 0.9,
            })
        return cleaned

    pipelines = []
    for r in as_list("pipelines"):
        tag = str(r.get("tag", "") or "").strip()
        if not tag:
            continue
        parts = []
        if r.get("from"):
            parts.append(f"起点: {r['from']}")
        if r.get("to"):
            parts.append(f"终点: {r['to']}")
        if r.get("spec"):
            parts.append(f"规格: {r['spec']}")
        pipelines.append({
            "tag": tag,
            "type": str(r.get("type", "") or "").strip() or "管线",
            "description": "；".join(parts),
            "confidence": 0.9,
        })

    findings_raw = result.get("findings", [])
    findings = [str(x) for x in findings_raw if str(x).strip()] if isinstance(findings_raw, list) else []
    return {
        "summary": str(result.get("summary", "") or "").strip(),
        "flow": str(result.get("flow", "") or "").strip(),
        "equipment": clean_rows(as_list("equipment")),
        "instruments": clean_rows(as_list("instruments")),
        "pipelines": pipelines,
        "findings": findings,
    }


def analyze(
    images: list,
    *,
    api_key: str,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 180,
) -> dict:
    """调用视觉大模型分析多页图纸。"""
    content: list[dict] = [{"type": "text", "text": USER_PROMPT}]
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_to_b64_png(img)}"},
        })

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    # 推理模型使用新的输出上限参数，并保留其默认采样设置。
    if model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        payload["max_completion_tokens"] = payload.pop("max_tokens")
        payload.pop("temperature")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        content_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"模型响应结构异常: {data}") from e

    if isinstance(content_text, list):  # 某些实现返回分段 content
        content_text = "".join(
            p.get("text", "") for p in content_text if isinstance(p, dict)
        )

    parsed = _extract_json(content_text)
    return _normalize(parsed)
