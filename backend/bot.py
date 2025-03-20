import os
from dotenv import load_dotenv
import telegram
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import CommandHandler, MessageHandler, filters
import telegram.ext
import asyncio
import sqlite3
from contextlib import contextmanager
from pydantic import BaseModel
from typing import Optional, List

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

# Функция для инициализации базы данных
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                ozon_api_token TEXT,
                ozon_client_id TEXT,
                last_updated TIMESTAMP
            )
        ''')
        conn.commit()

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

def get_main_keyboard():
    """Создает клавиатуру с основными командами"""
    keyboard = [
        [KeyboardButton('/start'), KeyboardButton('/help')],
        [KeyboardButton('/set_token'), KeyboardButton('/status')],
        [KeyboardButton('/delete_tokens')]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def set_bot_commands(bot):
    """Устанавливает команды бота с описаниями"""
    commands = [
        BotCommand("start", "Начать работу с ботом и получить приветствие"),
        BotCommand("help", "Получить справку по командам"),
        BotCommand("set_token", "Установить API токены Ozon"),
        BotCommand("status", "Проверить статус API токенов"),
        BotCommand("delete_tokens", "Удалить сохраненные API токены")
    ]
    await bot.set_my_commands(commands)

async def start(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! 👋\n\n"
        f"Я бот для работы с API Ozon. Я помогу вам анализировать данные с вашего магазина на Ozon, "
        f"отслеживать продажи, управлять товарами и получать аналитику.\n\n"
        f"Для начала работы установите API токены Ozon с помощью команды /set_token.\n\n"
        f"Доступные команды:\n"
        f"🔑 /set_token - установить API токены\n"
        f"ℹ️ /status - проверить статус API токенов\n"
        f"❌ /delete_tokens - удалить API токены\n"
        f"❓ /help - показать справку",
        reply_markup=get_main_keyboard()
    )

async def set_token(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /set_token"""
    args = update.message.text.split()
    if len(args) == 1:
        # Пользователь ввел только команду без параметров
        await update.message.reply_text(
            "Для работы с API Ozon необходимо предоставить API ключ и Client ID.\n\n"
            "📝 *Как получить API ключ и Client ID:*\n"
            "1. Войдите в личный кабинет продавца Ozon\n"
            "2. Перейдите в раздел *API интеграция*\n"
            "3. Создайте новый ключ, если его еще нет\n"
            "4. Скопируйте Client ID и API ключ\n\n"
            "⚠️ *Важно:* Эти данные конфиденциальны и дают доступ к вашему магазину. "
            "Не сообщайте их третьим лицам!\n\n"
            "Формат команды:\n"
            "`/set_token OZON_API_TOKEN OZON_CLIENT_ID`\n\n"
            "Пример:\n"
            "`/set_token a1b2c3d4-e5f6-g7h8-i9j0 12345`",
            parse_mode="Markdown"
        )
        return

    if len(args) != 3:
        await update.message.reply_text(
            "⚠️ Некорректный формат команды!\n\n"
            "Использование: `/set_token OZON_API_TOKEN OZON_CLIENT_ID`\n\n"
            "Пример: `/set_token a1b2c3d4-e5f6-g7h8-i9j0 12345`",
            parse_mode="Markdown"
        )
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

    await update.message.reply_text(
        "✅ API токены успешно сохранены!\n\n"
        "Теперь вы можете использовать веб-интерфейс для анализа данных вашего магазина Ozon.\n"
        "Ваши токены надежно сохранены и будут использоваться для авторизации API запросов.",
        reply_markup=get_main_keyboard()
    )

async def status(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /status"""
    user_token = get_user_token(update.effective_user.id)
    if user_token:
        await update.message.reply_text(
            "✅ API токены установлены и готовы к использованию.\n\n"
            f"Client ID: `{user_token.ozon_client_id}`\n"
            f"API Token: `{user_token.ozon_api_token[:5]}...{user_token.ozon_api_token[-5:]}`\n\n"
            "Веб-интерфейс должен работать корректно с этими токенами.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ API токены не установлены.\n\n"
            "Пожалуйста, используйте команду /set_token для установки токенов Ozon API.",
            reply_markup=get_main_keyboard()
        )

async def delete_tokens(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /delete_tokens"""
    delete_user_token(update.effective_user.id)
    await update.message.reply_text(
        "✅ API токены удалены.\n\n"
        "Ваши данные больше не хранятся в системе. Для возобновления работы с веб-интерфейсом "
        "необходимо заново установить токены с помощью команды /set_token.",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    await update.message.reply_text(
        "📚 *Справка по Ozon Bot*\n\n"
        "Бот предоставляет интерфейс для работы с API Ozon и позволяет анализировать "
        "данные вашего магазина через удобный веб-интерфейс.\n\n"
        "*Доступные команды:*\n\n"
        "🚀 /start - начать работу с ботом\n"
        "🔑 /set_token - установить API токены Ozon\n"
        "ℹ️ /status - проверить статус API токенов\n"
        "❌ /delete_tokens - удалить API токены\n"
        "❓ /help - показать эту справку\n\n"
        "*Как использовать:*\n"
        "1. Получите API токен и Client ID в личном кабинете Ozon\n"
        "2. Установите их с помощью команды /set_token\n"
        "3. Перейдите в веб-интерфейс для работы с аналитикой\n\n"
        "При возникновении проблем используйте команду /status для проверки настроек.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def unknown_command(update: Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Обработчик неизвестных команд"""
    await update.message.reply_text(
        "🤔 Извините, я не понимаю эту команду.\n"
        "Используйте /help для получения списка доступных команд.",
        reply_markup=get_main_keyboard()
    )

def main():
    # Получаем токен бота из переменных окружения
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("Не установлена переменная окружения TELEGRAM_BOT_TOKEN")

    # Инициализируем базу данных
    init_db()

    # Создаем приложение
    application = telegram.ext.Application.builder().token(bot_token).build()

    # Устанавливаем команды бота с описаниями
    application.post_init = set_bot_commands

    # Регистрируем обработчики
    application.add_handler(telegram.ext.CommandHandler("start", start))
    application.add_handler(telegram.ext.CommandHandler("set_token", set_token))
    application.add_handler(telegram.ext.CommandHandler("status", status))
    application.add_handler(telegram.ext.CommandHandler("delete_tokens", delete_tokens))
    application.add_handler(telegram.ext.CommandHandler("help", help_command))
    
    # Обработчик неизвестных команд (должен быть добавлен последним)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Запускаем бота
    print("Запуск бота...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main() 