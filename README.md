# P&ID 图纸分析工具

上传 P&ID（管道及仪表流程图）图纸，自动提取设备、仪表、管线信息，支持导出 Excel 清单。

Render 部署请阅读 [DEPLOY.md](DEPLOY.md)。本次部署配置为 Docker、Oregon、Free 和 `PID_MODE=ai`，优先验证 AI 图纸分析；需要双引擎时可改为 `PID_MODE=both` 并检查内存占用。

## 功能特性

- **多格式输入**：PNG / JPG / BMP / WEBP / TIFF / PDF（多页 PDF 自动逐页识别）
- **双分析引擎**：
  - **本地智能识别（推荐，免 API）**：深度学习 OCR（RapidOCR，PaddleOCR 模型）+ OpenCV 图元检测（仪表气泡、管线、设备框），识别力远超传统 Tesseract，离线可用
  - **AI 视觉大模型**：兼容 OpenAI 接口（GPT-4V、通义千问 VL、GLM-4V 等），可额外识别工艺物料流向与图纸概要
- **结构化结果**：设备 / 仪表 / 管线三个清单 + 图纸概要 + 物料流向 + 发现建议
- **一键导出 Excel**：含概览、设备清单、仪表清单、管线清单、发现与建议共 5 个工作表

## 快速开始

```bash
# 1. 安装依赖（需系统已装 tesseract-ocr 与 poppler-utils）
pip install -r requirements.txt

# 2. 启动服务
python -m uvicorn app:app --host 0.0.0.0 --port 8000

# 3. 浏览器打开 http://localhost:8000
```

> Ubuntu 下如缺少系统依赖：`sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim poppler-utils`

## 使用方式

1. **上传图纸**：拖拽或点击上传图片 / PDF
2. **选择引擎**：
   - 默认「本地智能识别」——深度学习 OCR + 图元检测，开箱即用，无需任何配置
   - 有 API Key → 选「AI 视觉大模型」，填入 API Key 与模型名（如 `gpt-6-luna`）；使用其他兼容服务时填写该服务提供的 Base URL 与视觉模型名称。
3. **点击「开始分析」**，右侧展示结构化结果
4. **点击「导出 Excel」** 下载清单

## 本地识别引擎原理

1. **深度学习 OCR**：RapidOCR（PaddleOCR PP-OCR 模型的 ONNX 推理版）提取图纸全部文字与坐标，识别力远超 Tesseract，对复杂位号（`PSV-2001`、`2"-PV-2001-A1A`、`150-PG-1001`）支持良好
2. **CV 图元检测**：OpenCV 霍夫圆检测仪表气泡、霍夫线检测管线、轮廓检测设备框
3. **空间关联 + 规则**：ISA 位号/管线号解析，结合「文字是否在仪表圈内、是否靠近管线」等空间关系修正归属，并过滤日期等误报

## 分析结果说明

| 字段 | 说明 |
|------|------|
| equipment | 设备清单（位号 / 类型 / 说明），前缀如 V、P、E、T、TK、R、K 等 |
| instruments | 仪表清单，ISA 位号如 PI、TI、FI、FV、PSV 等 |
| pipelines | 管线清单（管线号 / 介质 / 起终点规格），如 4"-PG-1001 |
| flow | 工艺物料流向（仅 AI 模式） |
| findings | 审查发现与建议 |

## 项目结构

```
pid-analyzer/
├── app.py                  # FastAPI 后端（上传/分析/导出）
├── analyzer/
│   ├── ai_analyzer.py      # AI 视觉大模型分析（OpenAI 兼容）
│   ├── local_analyzer.py   # 本地增强分析（规则 + 空间关联）
│   ├── ocr_engine.py       # OCR 引擎（RapidOCR 主 / Tesseract 兜底）
│   ├── cv_elements.py      # OpenCV 图元检测（气泡/管线/设备框）
│   ├── pdf_utils.py        # PDF 转图 / 缩放 / 预览
│   └── exporter.py         # Excel 导出
├── static/                 # 前端单页应用
├── requirements.txt
└── README.md
```

## 已知限制

- 本地引擎识别质量取决于图纸清晰度与文字密度，对低分辨率扫描件、手写体效果有限
- 本地引擎不推断工艺物料流向（AI 模式支持）
- AI 模式识别质量取决于所选模型能力，建议选择视觉能力较强的模型（qwen-vl-max / gpt-4o 等）
