FROM python:3.11-slim

WORKDIR /app

# poppler-utils：pdf2image 依赖，PDF 图纸转图必需
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY analyzer/ ./analyzer/
COPY static/ ./static/
COPY sample/ ./sample/

# PORT 由平台注入（Render/Railway/Fly 均自动设置），默认 8000
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
