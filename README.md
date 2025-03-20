# Ozon Bot

Telegram бот для работы с API Ozon.

## Функциональность

- Получение аналитики по товарам
- Отслеживание продаж
- Управление API токенами
- Уведомления о важных событиях

## Установка и запуск

1. Клонируйте репозиторий:
```bash
git clone https://github.com/Zhoposranchik/analitik2.git
cd analitik2
```

2. Создайте виртуальное окружение и активируйте его:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
# или
venv\Scripts\activate  # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` и добавьте необходимые переменные окружения:
```
TELEGRAM_BOT_TOKEN=your_bot_token
ENCRYPTION_KEY=your_encryption_key
```

5. Запустите бота:
```bash
cd backend
python bot.py
```

## Деплой на Render

1. Создайте аккаунт на [Render](https://render.com)
2. Подключите ваш GitHub репозиторий
3. Создайте новый Web Service
4. Укажите следующие переменные окружения в настройках сервиса:
   - `TELEGRAM_BOT_TOKEN`
   - `ENCRYPTION_KEY`
   - `PYTHON_VERSION=3.11.0`

## Структура проекта

```
.
├── backend/
│   ├── app.py      # FastAPI приложение
│   ├── bot.py      # Telegram бот
│   └── database.py # Работа с базой данных
├── requirements.txt
├── render.yaml
├── Procfile
└── README.md
```

## Использование

1. Найдите бота в Telegram
2. Отправьте команду `/start`
3. Следуйте инструкциям бота

## Команды

- `/start` - начать работу с ботом
- `/set_token OZON_API_TOKEN OZON_CLIENT_ID` - установить API токены
- `/status` - проверить статус API токенов
- `/delete_tokens` - удалить API токены
- `/help` - показать справку 