ARG PYTHON_VERSION=3.13
ARG BASE_IMAGE=python:${PYTHON_VERSION}-slim

FROM ${BASE_IMAGE} AS builder

WORKDIR /app

COPY requirements.txt .

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libfreetype6-dev \
        libpng-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --target=/app/python-packages -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt


FROM ${BASE_IMAGE} AS runtime

LABEL maintainer="kl8-feel-back"
LABEL version="1.0.0"
LABEL description="快乐8 数据分析 Web 应用 - arm64"

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

EXPOSE 5001

COPY --from=builder /app/python-packages /usr/local/lib/python${PYTHON_VERSION}/site-packages

COPY . .

ENV HOST=0.0.0.0 \
    PORT=5001 \
    KL8_DB_PATH=/data/kl8.db \
    TZ=Asia/Shanghai \
    PYTHONPATH=/usr/local/lib/python${PYTHON_VERSION}/site-packages

RUN useradd -m appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
