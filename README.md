# Ozon Bot - Telegram Mini App для продавцов Ozon

## Описание
Ozon Bot - это Telegram Mini App для продавцов на маркетплейсе Ozon, которое помогает анализировать продажи, отслеживать маржинальность и управлять товарами.

## Особенности
- Ввод API-токенов Ozon через Telegram бота для безопасности
- Анализ продаж с визуализацией данных
- Отслеживание маржинальности и ROI
- Управление себестоимостью товаров
- Отправка отчетов через Telegram
- Темная тема интерфейса

## Структура проекта
- `backend/` - FastAPI бэкенд для обработки запросов и взаимодействия с Ozon API
- `frontend/ozon-web/` - React-приложение для Telegram Mini App
- `requirements.txt` - Файл с зависимостями для Python

## Необходимые зависимости

### Бэкенд
- Python 3.8+
- FastAPI
- Uvicorn
- python-telegram-bot
- cryptography
- requests

### Фронтенд
- Node.js 14+
- React
- TypeScript

## Установка

### Бэкенд
```bash
cd backend
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate

# Вариант 1: Установка из requirements.txt (рекомендуется)
pip install -r ../requirements.txt

# Вариант 2: Установка зависимостей вручную
pip install fastapi uvicorn[standard] python-telegram-bot requests cryptography
```

### Фронтенд
```bash
cd frontend/ozon-web
npm install
```

## Запуск

### Бэкенд
```bash
cd backend
uvicorn app:app --host 0.0.0.0 --port 8002 --reload
```

### Фронтенд в режиме разработки
```bash
cd frontend/ozon-web
npm start
```

### Сборка фронтенда для продакшена
```bash
cd frontend/ozon-web
npm run build
```

## Настройка Telegram бота

1. Создайте бота через @BotFather в Telegram
2. Получите токен бота
3. Создайте мини-приложение через @BotFather:
   - Выберите вашего бота
   - Используйте команду /newapp
   - Следуйте инструкциям для создания мини-приложения
4. Обновите файл `backend/app.py` с полученным токеном бота
5. Настройте webhook для бота на эндпоинт `/telegram/webhook`
   ```
   https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=https://ваш-домен/telegram/webhook
   ```
6. Для локальной разработки используйте туннелинг (например, ngrok)
   ```
   ngrok http 8002
   ```

## Команды Telegram бота

- `/start` - Начать работу с ботом
- `/set_token OZON_API_TOKEN OZON_CLIENT_ID` - Установить API токены Ozon
- `/status` - Проверить статус API токенов
- `/delete_tokens` - Удалить API токены
- `/help` - Показать список доступных команд

## Интеграция с Ozon API

Для работы с Ozon API необходимо:
1. Получить API-токен и Client ID в личном кабинете Ozon
2. Передать их через команду `/set_token` в Telegram боте
3. API-токены хранятся в зашифрованном виде на сервере

## Безопасность

- API-токены хранятся в зашифрованном виде с использованием Fernet (библиотека cryptography)
- Аутентификация пользователей осуществляется через Telegram
- Для API-запросов используется API-ключ, который генерируется при сохранении токенов

## Разработка

### API-эндпоинты бэкенда

- `/products` - Получение списка товаров
- `/products/costs` - Сохранение и получение себестоимости товаров
- `/analytics` - Получение аналитики по продажам, маржинальности и ROI
- `/send_report` - Отправка отчета в Telegram
- `/telegram/webhook` - Обработка сообщений от Telegram
- `/telegram/user/{user_id}/tokens` - Получение токенов пользователя Telegram

### Структура фронтенда
- `src/App.tsx` - Основной компонент приложения
- `src/App.css` - Стили приложения

## Настройка темной темы

Приложение поддерживает как светлую, так и темную тему:
- Автоматически определяет системные настройки темы
- Переключатель темы в правом верхнем углу
- Настройки темы сохраняются в localStorage

## Лицензия
MIT 