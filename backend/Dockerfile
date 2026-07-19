FROM node:20-slim

# System deps for OpenCV / PaddleOCR / PaddlePaddle
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    libglib2.0-0 libgl1 libgomp1 \
    libsm6 libxext6 libxrender-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (heavy layer — cache it first)
COPY ai-worker/requirements.txt ./ai-worker/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r ./ai-worker/requirements.txt

# Pre-download PaddleOCR models at build time so they are baked into the image.
# Build and runtime both run as root → /root/.paddleocr is the same path at both
# stages. Without this, every cold start re-downloads ~16 MB of model tars before
# the first OCR call, adding latency and risking OOM during init.
RUN python3 -c "\
from paddleocr import PaddleOCR; \
PaddleOCR(lang='en', use_angle_cls=False, show_log=False, cpu_threads=4); \
print('PaddleOCR models ready')"

# Node dependencies
COPY backend/package*.json ./backend/
RUN cd backend && npm ci --only=production

# Application source
COPY backend/ ./backend/
COPY ai-worker/ ./ai-worker/

# /tmp/explodedview-storage is created at runtime by the app (STORAGE_PATH env var)

EXPOSE 5000

CMD ["node", "backend/src/app.js"]
