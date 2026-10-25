"""OCR 引擎封装：RapidOCR（主） + Tesseract（兜底）。

统一输出带坐标的词元列表，供规则匹配与空间关联使用。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class Word:
    text: str
    score: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


class OCREngine:
    def __init__(self, min_score: float = 0.5):
        self.min_score = min_score
        self._rapid = None
        self._rapid_failed = False

    # ---------- RapidOCR ----------
    def _get_rapid(self):
        if self._rapid is None and not self._rapid_failed:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._rapid = RapidOCR()
            except Exception:
                self._rapid_failed = True
        return self._rapid

    def _extract_rapid(self, img: Image.Image) -> list[Word]:
        engine = self._get_rapid()
        if engine is None:
            return []
        arr = np.array(img.convert("RGB"))
        result, _ = engine(arr)
        words: list[Word] = []
        if not result:
            return words
        for box, text, score in result:
            text = (text or "").strip()
            if not text or float(score) < self.min_score:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append(Word(
                text=text,
                score=float(score),
                bbox=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
            ))
        return words

    # ---------- Tesseract ----------
    def _extract_tesseract(self, img: Image.Image) -> list[Word]:
        import pytesseract
        try:
            langs = "chi_sim+eng"
            data = pytesseract.image_to_data(
                img, lang=langs, config="--psm 11",
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(
                img, lang="eng", config="--psm 11",
                output_type=pytesseract.Output.DICT,
            )
        words: list[Word] = []
        n = len(data["text"])
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = 0.0
            if conf < 30:
                continue
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            words.append(Word(text=text, score=conf / 100.0, bbox=(x, y, x + w, y + h)))
        return words

    # ---------- 统一入口 ----------
    def extract(self, img: Image.Image) -> list[Word]:
        """优先 RapidOCR，失败或为空时回退 Tesseract。"""
        words = self._extract_rapid(img)
        if words:
            return words
        return self._extract_tesseract(img)
