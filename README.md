# Ozon Analytics Bot

Telegram бот для аналитики продаж на Ozon.

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
python -m venv .venv
source .venv/bin/activate  # для Linux/Mac
# или
.venv\Scripts\activate  # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` в директории `backend` со следующими переменными:
```
TELEGRAM_BOT_TOKEN=ваш_токен_бота
ENCRYPTION_KEY=ваш_ключ_шифрования
```

5. Запустите бота:
```bash
cd backend
python bot.py
```

## Деплой на Render.com

1. Создайте аккаунт на [Render.com](https://render.com)
2. Подключите ваш GitHub репозиторий
3. Создайте два сервиса:
   - Web Service для API
   - Worker Service для бота
4. Настройте переменные окружения в настройках каждого сервиса
5. Запустите деплой

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