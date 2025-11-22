#!/bin/bash
# deploy.sh - Скрипт для обновления кода на сервере
SERVER="root@165.227.118.100"
REMOTE_DIR="/root/semantic-search/"

echo "🚀 Отправка файлов на сервер..."
# Отправляем код (исключая тяжелые папки и секреты)
rsync -avz --progress \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '.env' \
    --exclude 'games.db' \
    --exclude 'games.index' \
    --exclude 'chunk_map.json' \
    --exclude 'gcp-credentials.json' \
    . $SERVER:$REMOTE_DIR

echo "🔄 Перезапуск сервиса..."
ssh $SERVER "systemctl restart semantic-search.service"
ssh $SERVER "systemctl status semantic-search.service --no-pager | head -n 10"