# 智投研 AI · 部署镜像
# 适用：Render (Docker) / Railway (Dockerfile) / 任意支持 Docker 的平台
FROM python:3.11-slim

# 系统依赖：curl 用于数据层兜底，ca-certificates 保证 TLS
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 拷贝代码
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

WORKDIR /app/backend

ENV HOST=0.0.0.0
EXPOSE 8000

# 平台会注入 $PORT；本地默认 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
