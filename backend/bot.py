import os
from dotenv import load_dotenv
import telegram
from telegram import Update
import telegram.ext
import asyncio
import sqlite3
from contextlib import contextmanager
from pydantic import BaseModel
from typing import Optional

# Загружаем переменные окружения
load_dotenv()

# Модель для токенов пользователя
class UserToken(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    ozon_api_token: str
    ozon_client_id: str

@contextmanager
def get_db():
    conn = sqlite3.connect('user_tokens.db')
    try:
        yield conn
    finally:
        conn.close()

def save_user_token(user_token: UserToken):
    """Сохраняет токены пользователя в базу данных"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_tokens 
            (telegram_id, username, ozon_api_token, ozon_client_id, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_token.telegram_id, user_token.username, user_token.ozon_api_token, user_token.ozon_client_id))
        conn.commit()

def get_user_token(telegram_id: int) -> Optional[UserToken]:
    """Получает токены пользователя из базы данных"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_tokens WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        if row:
            return UserToken(
                telegram_id=row[1],
                username=row[2],
                ozon_api_token=row[3],
                ozon_client_id=row[4]
            )
        return None

def delete_user_token(telegram_id: int):
    """Удаляет токены пользователя из базы данных"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_tokens WHERE telegram_id = ?', (telegram_id,))
        conn.commit()

async def start(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет, {update.effective_user.username}! Я бот для работы с API Ozon.\n\n"
        f"Доступные команды:\n"
        f"/set_token OZON_API_TOKEN OZON_CLIENT_ID - установить API токены\n"
        f"/status - проверить статус API токенов\n"
        f"/delete_tokens - удалить API токены\n"
        f"/help - показать справку"
    )

async def set_token(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()
    if len(args) != 3:
        await update.message.reply_text("Использование: /set_token OZON_API_TOKEN OZON_CLIENT_ID")
        return

    ozon_api_token = args[1]
    ozon_client_id = args[2]

    user_token = UserToken(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        ozon_api_token=ozon_api_token,
        ozon_client_id=ozon_client_id
    )
    save_user_token(user_token)

    await update.message.reply_text("✅ API токены успешно сохранены!")

async def status(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    user_token = get_user_token(update.effective_user.id)
    if user_token:
        await update.message.reply_text("✅ API токены установлены")
    else:
        await update.message.reply_text("❌ API токены не установлены")

async def delete_tokens(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    delete_user_token(update.effective_user.id)
    await update.message.reply_text("✅ API токены удалены")

async def help_command(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Справка по командам:\n\n"
        "/start - начать работу с ботом\n"
        "/set_token OZON_API_TOKEN OZON_CLIENT_ID - установить API токены\n"
        "/status - проверить статус API токенов\n"
        "/delete_tokens - удалить API токены\n"
        "/help - показать эту справку"
    )

def main():
    # Получаем токен бота из переменных окружения
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("Не установлена переменная окружения TELEGRAM_BOT_TOKEN")

    # Создаем приложение
    application = telegram.ext.Application.builder().token(bot_token).build()

    # Регистрируем обработчики
    application.add_handler(telegram.ext.CommandHandler("start", start))
    application.add_handler(telegram.ext.CommandHandler("set_token", set_token))
    application.add_handler(telegram.ext.CommandHandler("status", status))
    application.add_handler(telegram.ext.CommandHandler("delete_tokens", delete_tokens))
    application.add_handler(telegram.ext.CommandHandler("help", help_command))

    # Запускаем бота
    print("Запуск бота...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main() 