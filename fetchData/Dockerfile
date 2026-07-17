# 快乐8 数据分析 Web 应用镜像
# 构建上下文：本目录（fetchData）
FROM python:3.13-slim

# 系统依赖：matplotlib 的 Agg 后端渲染需要 freetype/png，部分环境还需 libGL；tzdata 用于时区
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfreetype6 libpng16-16 libgl1 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

EXPOSE 5001

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（含仓库已带的 kl8.db 种子数据）
COPY . .

# 运行时配置：容器内必须监听 0.0.0.0；数据库落到挂载卷 /data
ENV HOST=0.0.0.0 \
    PORT=5001 \
    KL8_DB_PATH=/data/kl8.db \
    TZ=Asia/Shanghai

# 数据与代码分离，使用非 root 用户运行，便于持久化与安全性
RUN useradd -m appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
