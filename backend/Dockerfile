# backend/Dockerfile
# 作用：把 FastAPI 后端打包成 Docker 镜像，方便部署
# MVP 阶段主要用 docker-compose 本地开发，Dockerfile 是为后续部署准备的

FROM python:3.11-slim

# 设置工作目录（容器内的路径）
WORKDIR /app

# 先只复制 requirements.txt，利用 Docker 缓存层：
# 如果依赖没变，这一层不会重新 build，节省时间
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 再复制整个 backend 目录的代码
COPY . .

# 暴露端口（仅说明，实际端口映射在 docker-compose.yml 里配置）
EXPOSE 8000

# 启动命令：--reload 表示代码变更时自动重载（开发环境用）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
