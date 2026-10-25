"""本地增强分析器：深度学习 OCR + 计算机视觉图元检测 + 空间关联规则。

无需外部大模型 API，识别能力显著强于纯 Tesseract 方案：
- OCR：RapidOCR（PaddleOCR 模型 ONNX 推理），Tesseract 兜底
- CV：霍夫圆检测仪表气泡、霍夫线检测管线、轮廓检测设备框
- 规则：ISA 位号 + 管线号解析，结合文字-图元空间关系判定归属
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from PIL import Image

from . import cv_elements
from .ocr_engine import OCREngine

# ---- ISA/P&ID 位号前缀映射 ----
EQUIPMENT_PREFIX = {
    "TK": "储罐", "V": "容器", "D": "分离器/干燥器", "S": "分离器",
    "T": "塔", "C": "塔", "COL": "塔", "P": "泵", "E": "换热器",
    "HX": "换热器", "HE": "加热器", "R": "反应器", "K": "压缩机",
    "B": "风机/鼓风机", "F": "过滤器", "M": "混合器", "AG": "搅拌器",
    "PU": "泵", "PKG": "撬装设备", "BD": "鼓风机", "SEP": "分离器",
    "CP": "压缩机", "EX": "换热器", "PR": "泵",
}

INSTRUMENT_PREFIX = {
    "PI": "压力指示", "PT": "压力变送", "PC": "压力控制", "PIC": "压力指示控制",
    "PDI": "压差指示", "PDT": "压差变送", "PG": "压力表",
    "TI": "温度指示", "TT": "温度变送", "TC": "温度控制", "TIC": "温度指示控制",
    "TE": "温度元件", "TG": "温度计", "TW": "温度套管",
    "LI": "液位指示", "LT": "液位变送", "LC": "液位控制", "LIC": "液位指示控制",
    "LG": "液位计", "LS": "液位开关", "LIT": "液位指示变送",
    "FI": "流量指示", "FT": "流量变送", "FC": "流量控制", "FIC": "流量指示控制",
    "FE": "流量元件", "FQ": "流量累计", "FS": "流量开关", "FIT": "流量指示变送",
    "AI": "分析指示", "AT": "分析变送", "AE": "分析元件",
    "PSV": "安全阀", "PRV": "泄压阀", "RV": "安全/泄压阀", "SV": "安全阀",
    "PV": "压力调节阀", "TV": "温度调节阀", "LV": "液位调节阀", "FV": "流量调节阀",
    "PCV": "压力控制阀", "LCV": "液位控制阀", "TCV": "温度控制阀", "FCV": "流量控制阀",
    "XV": "开关阀", "CV": "调节阀", "SDV": "关断阀", "BDV": "放空阀", "BOV": "吹扫阀",
    "PS": "压力开关", "TS": "温度开关", "HS": "手操开关", "LSH": "液位高开关",
    "PSLL": "压力低低开关", "PSHH": "压力高高开关", "TSH": "温度高开关",
    "PSL": "压力低开关", "PSH": "压力高开关",
}

PIPE_PREFIX = {
    "PG": "工艺气体", "PL": "工艺液体", "PW": "工艺水", "CW": "循环水",
    "SW": "污水", "IA": "仪表空气", "PA": "工厂空气", "NG": "天然气",
    "FG": "燃料气", "FO": "燃料油", "RW": "原水", "DW": "脱盐水",
    "ST": "蒸汽", "LS": "低压蒸汽", "MS": "中压蒸汽", "HS": "高压蒸汽",
    "SC": "蒸汽冷凝液", "BFW": "锅炉给水", "N": "氮气", "CD": "化学药剂",
    "RW": "原水", "TW": "冷却水", "VP": "放空", "DR": "排放",
}

# 带管径的管线号：2"-PV-2001-A1A / 150-PG-1001 / 10°-PG-2001-A1A / 1.5"-CW-3002
# 组1=管径数字，组2=管径符号(可选)，组3=前缀，组4=编号，组5=规格段
PIPE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*([\"″°寸])?\s*[-/]?\s*([A-Z]{2,5})-(\d{2,5})(?:-([A-Z0-9]{1,8}))?\b"
)
# 裸位号：前缀(字母1-5) + 连字符 + 数字(2-5) + 可选尾字母
TAG_RE = re.compile(r"\b([A-Z]{1,5})-(\d{2,5})([A-Z]?)\b")

CN_EQUIPMENT_KEYS = ["泵", "塔", "罐", "换热器", "反应器", "压缩机", "风机", "分离器", "过滤器", "搅拌"]
CN_INSTRUMENT_KEYS = ["压力", "温度", "流量", "液位", "调节阀", "安全阀", "止回阀", "变送器", "液位计", "流量计"]

# 月份缩写，用于过滤「DD-MMM-YYYY」日期被误判为管线号
_MONTHS = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}

_ocr_engine: OCREngine | None = None


def _normalize_ocr_tags(text: str) -> str:
    """纠正 OCR 对位号中数字 1 被误识别为 l/I 的常见噪声。"""
    return re.sub(r"\b([A-Z]{1,5})[lI]?-(?:[lI])?(\d{2,5})\b", r"\1-\2", text)


@dataclass
class _Acc:
    equipment: list[dict] = field(default_factory=list)
    instruments: list[dict] = field(default_factory=list)
    pipelines: list[dict] = field(default_factory=list)
    seen_cores: set = field(default_factory=set)
    seen_tags: set = field(default_factory=set)


def _classify_tag(prefix: str) -> tuple[str, str] | None:
    """按前缀归类，优先级：设备 > 仪表 > 管线。"""
    p = prefix.upper()
    if p in EQUIPMENT_PREFIX:
        return ("equipment", EQUIPMENT_PREFIX[p])
    if p in INSTRUMENT_PREFIX:
        return ("instruments", INSTRUMENT_PREFIX[p])
    if p in PIPE_PREFIX:
        return ("pipelines", PIPE_PREFIX[p])
    return None


def _add(acc: _Acc, cat: str, tag: str, ctype: str, description: str, conf: float) -> None:
    if tag in acc.seen_tags:
        return
    acc.seen_tags.add(tag)
    getattr(acc, {"equipment": "equipment", "instruments": "instruments",
                  "pipelines": "pipelines"}[cat]).append({
        "tag": tag, "type": ctype, "description": description, "confidence": round(conf, 2),
    })


def _process_word(acc: _Acc, text: str, in_circle: bool, near_line: bool) -> None:
    """对单个 OCR 词元做位号/管线号提取与归类。"""
    # 第一步：带管径的管线号（最明确）
    for m in PIPE_RE.finditer(text):
        size, unit, prefix, num, suffix = m.group(1), m.group(2), m.group(3).upper(), m.group(4), m.group(5)
        if prefix in _MONTHS:  # 过滤日期 DD-MMM-YYYY
            continue
        core = f"{prefix}-{num}"
        if core in acc.seen_cores or core in acc.seen_tags:
            continue
        acc.seen_cores.add(core)
        if unit:  # 带英寸符号 → 英制管径
            tag = f'{size}{unit}-{core}' + (f"-{suffix}" if suffix else "")
            desc = f"管径 {size}″"
        else:  # 无符号 → 公称直径 DN
            tag = f'{size}-{core}' + (f"-{suffix}" if suffix else "")
            desc = f"公称直径 DN{size}"
        ctype = PIPE_PREFIX.get(prefix, "管线")
        _add(acc, "pipelines", tag, ctype, desc, 0.9)

    # 第二步：裸位号
    for m in TAG_RE.finditer(text):
        prefix = m.group(1).upper()
        num = m.group(2)
        core = f"{prefix}-{num}"
        tag = m.group(0)
        if core in acc.seen_cores or tag in acc.seen_tags:
            continue
        kind = _classify_tag(prefix)
        if kind is None:
            # 空间关系兜底：在仪表气泡内且形似位号 → 仪表
            if in_circle:
                acc.seen_cores.add(core)
                _add(acc, "instruments", tag, "仪表（气泡内）", "", 0.55)
            continue
        cat, ctype = kind
        acc.seen_cores.add(core)
        # 空间关系修正：靠近管线且分类为仪表/设备但带管线特征 → 保持原分类即可
        _add(acc, cat, tag, ctype, "", 0.85)


def analyze(img: Image.Image) -> dict:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = OCREngine()

    words = _ocr_engine.extract(img)

    # CV 图元检测（用于空间关联）
    circles = cv_elements.detect_instrument_circles(img)
    lines = cv_elements.detect_pipe_lines(img)
    rects = cv_elements.detect_rectangles(img)

    acc = _Acc()
    raw_parts: list[str] = []

    for w in words:
        raw_parts.append(w.text)
        text = _normalize_ocr_tags(w.text)
        cx, cy = w.center
        in_circle = any(cv_elements.point_in_circle(cx, cy, c) for c in circles)
        near_line = any(cv_elements.dist_point_to_segment(cx, cy, seg) < 12 for seg in lines[:200])
        _process_word(acc, text, in_circle, near_line)

    raw_text = "\n".join(raw_parts)
    findings: list[str] = []

    # 设备框内未识别到位号的，提示可能有设备遗漏
    findings.append(
        f"识别引擎：RapidOCR（深度学习），共识别 {len(words)} 个文本元素，"
        f"检测到 {len(circles)} 个仪表气泡、{len(lines)} 条管线、{len(rects)} 个设备框。"
    )
    findings.append(
        f"提取结果：{len(acc.equipment)} 台设备、{len(acc.instruments)} 个仪表、{len(acc.pipelines)} 条管线。"
    )
    if not words:
        findings.append("未识别到有效文字，可能为纯图形图纸或图像质量过低。")

    return {
        "raw_text": raw_text,
        "equipment": acc.equipment,
        "instruments": acc.instruments,
        "pipelines": acc.pipelines,
        "findings": findings,
    }
