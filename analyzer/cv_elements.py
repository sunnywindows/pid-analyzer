"""计算机视觉图元检测：仪表气泡圈、管线线段、设备边框。"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _gray_binary(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """灰度化 + 自适应二值化，返回 (灰度图, 二值图)。"""
    gray = np.array(img.convert("L"))
    bin_img = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 21, 11,
    )
    return gray, bin_img


def detect_instrument_circles(
    img: Image.Image,
    min_radius: int = 8,
    max_radius: int = 60,
) -> list[dict]:
    """检测 P&ID 仪表气泡（圆圈）。返回 [{cx, cy, r}]。"""
    gray, _ = _gray_binary(img)
    # 轻微模糊降噪后霍夫圆检测
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20,
        param1=80, param2=42,
        minRadius=min_radius, maxRadius=max_radius,
    )
    out: list[dict] = []
    if circles is None:
        return out
    for c in np.round(circles[0]).astype(int):
        cx, cy, r = int(c[0]), int(c[1]), int(c[2])
        if r > 0:
            out.append({"cx": cx, "cy": cy, "r": r})
    return out


def detect_pipe_lines(
    img: Image.Image,
    min_length: int = 90,
    max_gap: int = 30,
) -> list[dict]:
    """检测管线（长直线段）。返回 [{x1,y1,x2,y2,length}]。"""
    _, bin_img = _gray_binary(img)
    # 形态学开运算去噪，保留长直线
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, kernel, iterations=1)
    lines = cv2.HoughLinesP(
        cleaned, 1, np.pi / 180, threshold=80,
        minLineLength=min_length, maxLineGap=max_gap,
    )
    out: list[dict] = []
    if lines is None:
        return out
    for line in lines:
        x1, y1, x2, y2 = map(int, line[0])
        length = float(np.hypot(x2 - x1, y2 - y1))
        out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "length": length})
    # 按长度降序，便于后续取主线
    out.sort(key=lambda l: l["length"], reverse=True)
    return out


def detect_rectangles(
    img: Image.Image,
    min_area: int = 2000,
    max_area: int = 400000,
) -> list[dict]:
    """检测设备边框（矩形）。返回 [{x1,y1,x2,y2,w,h}]。"""
    _, bin_img = _gray_binary(img)
    contours, _ = cv2.findContours(bin_img, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out: list[dict] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if w > 20 and h > 20:
                out.append({"x1": x, "y1": y, "x2": x + w, "y2": y + h, "w": w, "h": h})
    return out


def point_in_rect(px: float, py: float, rect: dict) -> bool:
    return rect["x1"] <= px <= rect["x2"] and rect["y1"] <= py <= rect["y2"]


def point_in_circle(px: float, py: float, circ: dict, pad: float = 1.2) -> bool:
    dx, dy = px - circ["cx"], py - circ["cy"]
    return (dx * dx + dy * dy) <= (circ["r"] * pad) ** 2


def dist_point_to_segment(px: float, py: float, seg: dict) -> float:
    """点到线段的最短距离。"""
    x1, y1, x2, y2 = seg["x1"], seg["y1"], seg["x2"], seg["y2"]
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return float(np.hypot(px - x1, py - y1))
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return float(np.hypot(px - cx, py - cy))
