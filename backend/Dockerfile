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

# Node dependencies
COPY backend/package*.json ./backend/
RUN cd backend && npm ci --only=production

# Application source
COPY backend/ ./backend/
COPY ai-worker/ ./ai-worker/

# /tmp/explodedview-storage is created at runtime by the app (STORAGE_PATH env var)

EXPOSE 5000

CMD ["node", "backend/src/app.js"]
