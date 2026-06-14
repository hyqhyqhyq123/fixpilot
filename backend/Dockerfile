# backend/Dockerfile
# 作用：把 FastAPI 后端打包成 Docker 镜像，方便部署
# MVP 阶段主要用 docker-compose 本地开发，Dockerfile 是为后续部署准备的

FROM python:3.11-slim

WORKDIR /app

# git：Worker 内 clone 仓库；curl：健康检查（可选）
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
