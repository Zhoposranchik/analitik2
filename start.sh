#!/bin/bash

# Установка зависимостей
pip install -r requirements.txt

# Запуск бэкенда
cd backend
uvicorn app:app --host 0.0.0.0 --port ${PORT:-8002}
