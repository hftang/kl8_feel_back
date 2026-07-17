#!/bin/sh
set -e

# 若挂载卷为空（首次启动），用镜像内自带的种子 kl8.db 初始化，避免数据丢失
if [ ! -f "$KL8_DB_PATH" ] && [ -f /app/kl8.db ]; then
  cp /app/kl8.db "$KL8_DB_PATH"
fi

exec python /app/app.py
