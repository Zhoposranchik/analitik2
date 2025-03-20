from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks
import requests
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from cryptography.fernet import Fernet
from fastapi.security import APIKeyHeader
import hashlib
from dotenv import load_dotenv
import sqlite3
from contextlib import contextmanager
import telegram
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import sys
import importlib.util
from telegram.ext import ApplicationBuilder, ContextTypes
from telegram.ext import Application, CallbackContext

# Загружаем переменные окружения из .env файла
load_dotenv()

# Инициализация базы данных
def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                ozon_api_token TEXT,
                ozon_client_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect('user_tokens.db')
    try:
        yield conn
    finally:
        conn.close()

# Инициализируем базу данных при запуске
init_db()

# Обработка ошибок, если библиотеки не установлены
try:
    import telegram
except ImportError:
    # Создаем заглушку для telegram бота
    class TelegramBot:
        def __init__(self, token):
            self.token = token
            print("ВНИМАНИЕ: Модуль telegram не установлен. Используется заглушка.")

        async def send_message(self, chat_id, text):
            print(f"ЗАГЛУШКА: Отправка сообщения '{text}' в чат {chat_id}")
            return True

    class telegram:
        @staticmethod
        def Bot(token):
            return TelegramBot(token)

# Генерация ключа для шифрования (в реальном приложении должен храниться в защищенном месте)
# Для реального приложения используйте переменные окружения или хранилище секретов
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key())
cipher_suite = Fernet(ENCRYPTION_KEY)

# Модели данных для API
class UserToken(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    ozon_api_token: str
    ozon_client_id: str

class ProductCost(BaseModel):
    product_id: int
    offer_id: str
    cost: float

class NotificationSettings(BaseModel):
    threshold: float  # Порог маржинальности для уведомлений

class ApiTokens(BaseModel):
    ozon_api_token: str
    ozon_client_id: str
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

# Модель для телеграм-пользователей
class TelegramUser(BaseModel):
    user_id: int
    username: Optional[str] = None
    api_tokens: Optional[ApiTokens] = None

# Настройки Telegram бота (загружаем из переменных окружения)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
    raise ValueError("Не установлены необходимые переменные окружения: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")

# Создаем приложение
app = FastAPI()

# Добавляем CORS middleware для работы с фронтендом
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zhoposranchik.github.io",            # Корневой домен GitHub Pages
        "https://zhoposranchik.github.io/analitik2",  # Основной URL приложения
        "https://zhoposranchik.github.io/analitik2/", # URL с завершающим слешем
        "http://localhost:3000",                      # Локальная разработка React
        "http://127.0.0.1:3000"                       # Альтернативный локальный URL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# База данных пользователей (в реальном приложении использовать настоящую БД)
users_db = {}

# База данных телеграм-пользователей
telegram_users_db = {}

# Функции для шифрования и дешифрования токенов
def encrypt_tokens(tokens: dict) -> str:
    """Шифрует токены API"""
    tokens_json = json.dumps(tokens)
    encrypted_tokens = cipher_suite.encrypt(tokens_json.encode())
    return encrypted_tokens.decode()

def decrypt_tokens(encrypted_tokens: str) -> dict:
    """Дешифрует токены API"""
    try:
        decrypted_tokens = cipher_suite.decrypt(encrypted_tokens.encode())
        return json.loads(decrypted_tokens)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка расшифровки токенов: {str(e)}")

# Функция для получения токенов из заголовка запроса
api_key_header = APIKeyHeader(name="X-API-Key")

async def get_api_tokens(api_key: str = Depends(api_key_header)):
    """Получает токены API из заголовка запроса"""
    try:
        user_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if user_hash not in users_db:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        encrypted_tokens = users_db[user_hash]["tokens"]
        tokens = decrypt_tokens(encrypted_tokens)
        return tokens
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Ошибка аутентификации: {str(e)}")

# Функции для работы с токенами
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

# Инициализация бота
try:
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    print("Telegram бот успешно инициализирован")
except Exception as e:
    print(f"Ошибка инициализации Telegram бота: {str(e)}")
    # Создаем заглушку, если бот не удалось инициализировать
    class BotStub:
        async def send_message(self, chat_id, text):
            print(f"[БОТ-ЗАГЛУШКА] Отправка сообщения в чат {chat_id}: {text}")
    bot = BotStub()

# Функция для создания клавиатуры с кнопками
def get_main_keyboard():
    """Создает клавиатуру с основными командами"""
    keyboard = [
        [KeyboardButton("Запустить бота 🚀"), KeyboardButton("Помощь ❓")],
        [KeyboardButton("Установить токены 🔑"), KeyboardButton("Проверить статус ℹ️")],
        [KeyboardButton("Статистика 📊"), KeyboardButton("Удалить токены ❌")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Функция для создания инлайн клавиатуры с кнопкой приложения
def get_app_button():
    """Создает инлайн клавиатуру с кнопкой для открытия приложения"""
    keyboard = [[InlineKeyboardButton("🚀 Открыть приложение Ozon Analytics", url="https://zhoposranchik.github.io/analitik2/")]]
    return InlineKeyboardMarkup(keyboard)

# Функция для настройки меню команд
async def setup_bot_commands():
    """Настраивает меню команд бота"""
    try:
        commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("help", "Помощь и справка"),
            BotCommand("set_token", "Установить токены Ozon"),
            BotCommand("status", "Проверить статус"),
            BotCommand("stats", "Получить статистику"),
            BotCommand("verify", "Проверить валидность токенов"),
            BotCommand("delete_tokens", "Удалить токены")
        ]
        
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands",
            json={"commands": [{"command": cmd.command, "description": cmd.description} for cmd in commands]}
        )
        
        if response.status_code == 200 and response.json().get("ok"):
            print("✅ Меню команд успешно настроено!")
        else:
            print(f"❌ Ошибка настройки меню команд: {response.json()}")
    except Exception as e:
        print(f"Ошибка настройки меню команд: {str(e)}")

# Добавляем простую систему состояний для диалога с пользователем
user_states = {}  # Хранит текущее состояние диалога пользователя и промежуточные данные

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команды от пользователя"""
    command = update.message.text.split()[0][1:]  # удаляем символ / и берем первое слово
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Создаем клавиатуру
    reply_markup = ReplyKeyboardMarkup(
        [
            ["Установить токены 🔑", "Проверить статус ℹ️"],
            ["Статистика 📊", "Помощь ❓"],
            ["Удалить токены ❌"]
        ],
        resize_keyboard=True
    )
    
    if command == "start":
        # Сбрасываем состояние пользователя
        user_states[user_id] = "idle"
        
        # Приветственное сообщение
        await update.message.reply_text(
            f"👋 Привет! Я бот для мониторинга вашего магазина Ozon.\n\n"
            "Для доступа к аналитике и управлению магазином вам нужно настроить токены API Ozon.\n\n"
            "Используйте команду /set_token чтобы настроить API токен и Client ID.\n"
            "Или нажмите кнопку ниже:",
            reply_markup=reply_markup
        )
        
        # Создаем инлайн клавиатуру с кнопкой для открытия веб-приложения
        app_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Открыть веб-приложение", web_app=WebAppInfo(url=WEB_APP_URL))]
        ])
        
        # Отправляем второе сообщение с кнопкой веб-приложения
        await update.message.reply_text(
            "Также вы можете сразу открыть веб-приложение:",
            reply_markup=app_button
        )
    
    elif command == "set_token":
        # Устанавливаем состояние пользователя
        user_states[user_id] = "waiting_for_api_token"
        
        # Инструкции по получению и установке токенов
        await update.message.reply_text(
            "🔑 *Настройка API токена и Client ID*\n\n"
            "*Шаг 1:* Отправьте мне ваш API токен Ozon.\n\n"
            "Чтобы получить API токен и Client ID:\n"
            "1️⃣ Войдите в личный кабинет Ozon Seller: https://seller.ozon.ru\n"
            "2️⃣ Перейдите в раздел *API интеграция*\n"
            "3️⃣ Нажмите кнопку *Создать токен* и скопируйте его\n"
            "4️⃣ Скопируйте также ваш *Client ID* из той же страницы\n\n"
            "📋 Просто отправьте API токен в следующем сообщении:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    elif command == "status":
        # Проверяем статус токенов пользователя
        tokens = await get_user_tokens(user_id)
        
        if tokens:
            # Проверяем валидность токенов
            is_valid, message = await verify_ozon_tokens(tokens.ozon_api_token, tokens.ozon_client_id)
            
            if is_valid:
                # Форматируем дату последнего использования
                last_used = tokens.last_used
                last_used_str = last_used.strftime("%d.%m.%Y %H:%M:%S") if last_used else "никогда"
                
                await update.message.reply_text(
                    "✅ *Ваши токены активны и действительны*\n\n"
                    f"API токен: `{tokens.ozon_api_token[:5]}...{tokens.ozon_api_token[-5:]}`\n"
                    f"Client ID: `{tokens.ozon_client_id}`\n"
                    f"Последнее использование: {last_used_str}\n\n"
                    "Вы можете использовать веб-приложение для анализа данных или нажать /delete_tokens для удаления токенов.",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    f"⚠️ *Ваши токены недействительны*\n\n"
                    f"Ошибка: {message}\n\n"
                    "Рекомендуется установить новые токены с помощью команды /set_token",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                "❌ У вас не настроены токены API Ozon.\n\n"
                "Используйте команду /set_token чтобы настроить API токен и Client ID.",
                reply_markup=reply_markup
            )
    
    elif command == "delete_tokens":
        # Удаляем токены пользователя из базы данных
        success = await delete_user_tokens(user_id)
        
        if success:
            # Сбрасываем состояние пользователя
            user_states[user_id] = "idle"
            
            await update.message.reply_text(
                "✅ Ваши токены успешно удалены.\n\n"
                "Вы можете установить новые токены с помощью команды /set_token.",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "❌ Произошла ошибка при удалении токенов.\n\n"
                "Возможно, у вас нет сохраненных токенов.",
                reply_markup=reply_markup
            )
    
    elif command == "verify":
        # Проверяем токены пользователя
        tokens = await get_user_tokens(user_id)
        
        if tokens:
            # Отправляем сообщение о проверке
            progress_message = await update.message.reply_text("🔄 Проверяем ваши токены, пожалуйста, подождите...")
            
            # Проверяем валидность токенов
            is_valid, message = await verify_ozon_tokens(tokens.ozon_api_token, tokens.ozon_client_id)
            
            if is_valid:
                # Обновляем сообщение с результатом проверки
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text="✅ Ваши токены действительны и активны.",
                    reply_markup=reply_markup
                )
            else:
                # Обновляем сообщение с ошибкой
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text=f"❌ Ошибка проверки токенов: {message}\n\n"
                    "Рекомендуется установить новые токены с помощью команды /set_token",
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(
                "❌ У вас не настроены токены API Ozon.\n\n"
                "Используйте команду /set_token чтобы настроить API токен и Client ID.",
                reply_markup=reply_markup
            )
    
    elif command == "stats":
        # Получаем статистику из Ozon API
        tokens = await get_user_tokens(user_id)
        
        if not tokens:
            await update.message.reply_text(
                "❌ У вас не настроены токены API Ozon.\n\n"
                "Используйте команду /set_token чтобы настроить API токен и Client ID.",
                reply_markup=reply_markup
            )
            return
        
        # Отправляем сообщение о загрузке статистики
        progress_message = await update.message.reply_text("🔄 Загружаем данные из Ozon API, пожалуйста, подождите...")
        
        try:
            # Получаем данные аналитики из API
            data = await get_ozon_analytics(tokens.ozon_api_token, tokens.ozon_client_id)
            
            if isinstance(data, dict) and "result" in data:
                # Обрабатываем статистику
                analytics = data["result"]
                
                # Формируем сообщение со статистикой
                stats_message = "*📊 Статистика вашего магазина Ozon*\n\n"
                
                # Добавляем информацию о периоде
                stats_message += f"📆 *Период:* {analytics.get('period', 'Текущий период')}\n\n"
                
                # Добавляем основные показатели
                if 'metrics' in analytics:
                    for metric in analytics['metrics']:
                        name = metric.get('name', 'Показатель')
                        value = metric.get('value', '0')
                        stats_message += f"• *{name}:* {value}\n"
                
                # Обновляем сообщение со статистикой
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text=stats_message,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                # Если данные не получены или в неверном формате
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text="❌ Не удалось получить статистику из Ozon API.\n\n"
                    "Возможно, ваши токены недействительны или произошла ошибка API.",
                    reply_markup=reply_markup
                )
        except Exception as e:
            # Обновляем сообщение с ошибкой
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_message.message_id,
                text=f"❌ Ошибка при получении статистики: {str(e)}\n\n"
                "Попробуйте позже или проверьте ваши токены с помощью команды /verify",
                reply_markup=reply_markup
            )
    
    elif command == "help" or command == "помощь":
        # Выводим справку по доступным командам
        await update.message.reply_text(
            "🤖 *Справка по командам*\n\n"
            "/start - Запустить бота\n"
            "/set_token - Настроить API токен и Client ID\n"
            "/status - Проверить статус ваших токенов\n"
            "/verify - Проверить валидность ваших токенов\n"
            "/stats - Получить статистику из Ozon API\n"
            "/delete_tokens - Удалить сохраненные токены\n"
            "/help - Показать это сообщение\n\n"
            "Для начала работы настройте токены с помощью команды /set_token",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    elif command == "cancel":
        # Сбрасываем состояние пользователя
        user_states[user_id] = "idle"
        
        await update.message.reply_text(
            "✅ Операция отменена.\n\n"
            "Вы можете использовать другие команды или кнопки ниже:",
            reply_markup=reply_markup
        )
    
    else:
        # Неизвестная команда
        await update.message.reply_text(
            "❓ Неизвестная команда. Используйте /help для получения справки по доступным командам.",
            reply_markup=reply_markup
        )

# Функция для обработки текстовых сообщений (не команд)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает обычные текстовые сообщения от пользователя"""
    user_id = update.effective_user.id
    message_text = update.message.text.strip()

    # Проверяем, есть ли пользователь в словаре состояний
    if user_id not in user_states:
        await update.message.reply_text(
            "Для начала работы с ботом, пожалуйста, используйте команду /start"
        )
        return

    current_state = user_states[user_id]
    
    # Если пользователь в состоянии ожидания API токена
    if current_state == "waiting_for_api_token":
        # Очищаем токен от кавычек и пробелов
        cleaned_token = message_text.strip("\"' \t\n")
        
        # Пользователь слишком коротким ответом вводит токен
        if len(cleaned_token) < 10:
            await update.message.reply_text(
                "❌ Некорректный формат API токена. Токен должен быть достаточно длинным.\n\n"
                "🔑 API токен обычно имеет вид XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX\n\n"
                "Пожалуйста, отправьте правильный API токен или используйте /cancel для отмены."
            )
            return
        
        # Сохраняем токен в состоянии пользователя
        user_states[user_id] = {"state": "waiting_for_client_id", "api_token": cleaned_token}
        
        await update.message.reply_text(
            "✅ API токен сохранен\n\n"
            "Теперь, пожалуйста, отправьте ID клиента (Client ID).\n"
            "Вы можете найти его в личном кабинете Ozon в разделе API."
        )
        return
        
    # Если пользователь в состоянии ожидания Client ID
    elif isinstance(current_state, dict) and current_state.get("state") == "waiting_for_client_id":
        # Очищаем от кавычек и пробелов
        cleaned_client_id = message_text.strip("\"' \t\n")
        
        # Проверяем формат Client ID (допускаем только цифры)
        if not cleaned_client_id.isdigit():
            await update.message.reply_text(
                "❌ Некорректный формат Client ID. ID клиента должен состоять только из цифр.\n\n"
                "Пожалуйста, отправьте правильный Client ID или используйте /cancel для отмены."
            )
            return
        
        api_token = current_state.get("api_token", "")
        
        # Отправляем сообщение о проверке токенов
        progress_message = await update.message.reply_text("🔄 Проверяем ваши токены, пожалуйста, подождите...")
        
        # Проверяем токены перед сохранением
        is_valid, error_message = await verify_ozon_tokens(api_token, cleaned_client_id)
        
        if is_valid:
            # Сохраняем токены в базу данных
            success = await save_user_token(user_id, api_token, cleaned_client_id)
            
            if success:
                # Очищаем состояние пользователя
                user_states[user_id] = "idle"
                
                # Обновляем прогресс-сообщение
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text="✅ Токены успешно проверены и сохранены!\n\n"
                    "Теперь вы можете использовать веб-приложение для анализа ваших товаров на Ozon."
                )
            else:
                # Устанавливаем состояние ожидания API токена
                user_states[user_id] = "waiting_for_api_token"
                
                # Обновляем прогресс-сообщение
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text="❌ Произошла ошибка при сохранении токенов. Пожалуйста, попробуйте еще раз."
                )
        else:
            # Устанавливаем состояние ожидания API токена
            user_states[user_id] = "waiting_for_api_token"
            
            # Обновляем прогресс-сообщение с подробной информацией об ошибке
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_message.message_id,
                text=f"❌ Ошибка проверки токенов: {error_message}\n\n"
                "Пожалуйста, убедитесь, что вы правильно ввели API токен и Client ID. "
                "Начните процесс заново с команды /set_token."
            )
        return
    
    # Для всех других состояний
    await update.message.reply_text(
        "Я не понимаю этой команды. Пожалуйста, используйте /help чтобы увидеть список доступных команд."
    )

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, update: dict):
    """Обработчик вебхука от Telegram"""
    if token != TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "Неверный токен бота"}
    
    try:
        # Преобразуем dict в объект Update
        update_obj = Update.from_dict(update)
        
        # Создаем объект приложения и контекста
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        context = CallbackContext(application)
        
        # Проверяем, что это сообщение (может быть другой тип обновления)
        if update_obj.message:
            # Если это команда
            if update_obj.message.text and update_obj.message.text.startswith('/'):
                await handle_command(update_obj, context)
            # Если это обычный текст
            elif update_obj.message.text:
                await handle_message(update_obj, context)
        
        return {"status": "ok"}
    except Exception as e:
        print(f"Ошибка при обработке вебхука: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/telegram/user/{user_id}/tokens")
async def get_telegram_user_tokens(user_id: int):
    """Получает API токены пользователя Telegram"""
    user_token = get_user_token(user_id)
    
    if not user_token:
        raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
    
    # Возвращаем данные в формате, который ожидает фронтенд
    return {
        "ozon_api_token": user_token.ozon_api_token,
        "ozon_client_id": user_token.ozon_client_id
    }

# Функция проверки актуальности токенов через API Ozon
async def verify_ozon_tokens(api_token: str, client_id: str) -> tuple:
    """Проверяет валидность токенов Ozon, отправляя тестовый запрос к API"""
    try:
        # URL для тестового запроса (получение информации о категориях)
        url = "https://api-seller.ozon.ru/v1/category/tree"
        
        # Заголовки запроса
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_token,
            "Content-Type": "application/json"
        }
        
        # Тело запроса (пустой объект для этого метода)
        payload = {}
        
        # Записываем в лог информацию о запросе для отладки (без вывода полного токена)
        print(f"Отправка запроса к Ozon API: URL={url}, Client-Id={client_id}, Api-Key={api_token[:5]}...{api_token[-5:] if len(api_token) > 10 else ''}")
        
        # Отправляем запрос с таймаутом
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # Записываем в лог ответ
        print(f"Получен ответ от Ozon API: Статус={response.status_code}")
        
        # Проверяем статус ответа
        if response.status_code == 200:
            print("Токены валидны, получен успешный ответ")
            return True, "Токены действительны"
        elif response.status_code == 404:
            error_message = "Ошибка 404: API метод не найден. Возможно, URL запроса устарел или изменен."
            print(error_message)
            return False, error_message
        elif response.status_code == 403:
            error_message = "Ошибка 403: Доступ запрещен. Токены недействительны или не имеют необходимых прав."
            print(error_message)
            return False, error_message
        elif response.status_code == 401:
            error_message = "Ошибка 401: Не авторизован. Проверьте правильность API токена и Client ID."
            print(error_message)
            return False, error_message
        else:
            # Пытаемся извлечь описание ошибки из ответа JSON
            error_detail = ""
            try:
                error_json = response.json()
                if 'error' in error_json:
                    error_detail = f": {error_json['error']}"
                elif 'message' in error_json:
                    error_detail = f": {error_json['message']}"
            except:
                # Если не удалось распарсить JSON ответ
                error_detail = f": {response.text[:100]}..." if len(response.text) > 100 else f": {response.text}"
            
            error_message = f"Ошибка при проверке токенов: HTTP {response.status_code}{error_detail}"
            print(error_message)
            return False, error_message
        
    except requests.exceptions.Timeout:
        error_message = "Ошибка: Превышено время ожидания ответа от Ozon API. Проверьте подключение к интернету."
        print(error_message)
        return False, error_message
    except requests.exceptions.ConnectionError:
        error_message = "Ошибка соединения: Не удалось подключиться к Ozon API. Проверьте подключение к интернету."
        print(error_message)
        return False, error_message
    except Exception as e:
        error_message = f"Неизвестная ошибка при проверке токенов: {str(e)}"
        print(error_message)
        return False, error_message

# Обновляем функцию save_user_token для проверки токенов перед сохранением
async def save_user_token_with_verification(user_token: UserToken) -> tuple:
    """Проверяет токены и сохраняет их в базу данных"""
    # Проверяем токены через API Ozon
    is_valid, message = await verify_ozon_tokens(
        user_token.ozon_api_token, 
        user_token.ozon_client_id
    )
    
    if not is_valid:
        return False, message
    
    # Если токены валидны, сохраняем в базу данных
    try:
        save_user_token(user_token)
        return True, "Токены успешно сохранены"
    except Exception as e:
        return False, f"Ошибка при сохранении токенов: {str(e)}"

# Функция для обновления времени последнего использования токенов
def update_token_usage(telegram_id: int):
    """Обновляет время последнего использования токенов"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_tokens 
            SET last_updated = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        ''', (telegram_id,))
        conn.commit()

# Добавляем новый эндпоинт для проверки токенов
@app.post("/api/tokens/verify")
async def verify_tokens(tokens: ApiTokens):
    """Проверяет валидность токенов Ozon без сохранения"""
    is_valid, message = await verify_ozon_tokens(
        tokens.ozon_api_token,
        tokens.ozon_client_id
    )
    
    if is_valid:
        return {"status": "success", "message": message}
    else:
        raise HTTPException(status_code=400, detail=message)

# Обновляем эндпоинт auth_by_telegram_id для обновления времени использования токенов
@app.get("/api/auth/telegram/{telegram_id}")
async def auth_by_telegram_id(telegram_id: int):
    """Авторизация по Telegram ID и получение токенов для фронтенда"""
    user_token = get_user_token(telegram_id)
    
    if not user_token:
        raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены. Пожалуйста, установите токены через Telegram бота.")
    
    # Обновляем время последнего использования токенов
    update_token_usage(telegram_id)
    
    # Генерируем API ключ для использования на фронтенде
    api_key = f"tg-user-{telegram_id}-{datetime.now().timestamp()}"
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Создаем объект с токенами для сохранения
    tokens = {
        "ozon_api_token": user_token.ozon_api_token,
        "ozon_client_id": user_token.ozon_client_id,
        "telegram_id": telegram_id
    }
    
    # Проверяем актуальность токенов
    is_valid, message = await verify_ozon_tokens(user_token.ozon_api_token, user_token.ozon_client_id)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Токены больше не действительны. Пожалуйста, обновите их через Telegram бота. Ошибка: {message}")
    
    # Шифруем и сохраняем токены
    encrypted_tokens = encrypt_tokens(tokens)
    users_db[user_hash] = {
        "tokens": encrypted_tokens,
        "created_at": datetime.now().isoformat(),
        "api_key": api_key,
        "telegram_id": telegram_id
    }
    
    return {
        "api_key": api_key,
        "message": "Авторизация успешна",
        "ozon_api_token": user_token.ozon_api_token,
        "ozon_client_id": user_token.ozon_client_id
    }

@app.get("/telegram/users")
async def get_telegram_users():
    """Получает список пользователей Telegram (только для админа)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT telegram_id, username, created_at FROM user_tokens')
        users = cursor.fetchall()
        return {"users": [{"telegram_id": u[0], "username": u[1], "created_at": u[2]} for u in users]}

# Инициализация и настройка вебхуков для Telegram бота
async def setup_webhook():
    """Настраивает вебхук для бота"""
    try:
        # Получаем URL сервиса из переменных окружения (Render.com автоматически устанавливает эту переменную)
        render_external_url = os.getenv("RENDER_EXTERNAL_URL")
        
        if render_external_url:
            webhook_url = f"{render_external_url}/telegram/webhook"
            print(f"Настройка вебхука на Render.com: {webhook_url}")
            # Устанавливаем вебхук
            response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={webhook_url}"
            )
            print(f"Ответ Telegram API: {response.json()}")
            
            if response.status_code == 200 and response.json().get("ok"):
                print("✅ Вебхук успешно настроен!")
            else:
                print(f"❌ Ошибка настройки вебхука: {response.json()}")
            
            # Настраиваем меню команд
            await setup_bot_commands()
        else:
            print("⚠️ RENDER_EXTERNAL_URL не установлен. Невозможно настроить вебхук автоматически.")
            print("⚠️ Вебхук не настроен - для работы используйте ручное тестирование через эндпоинт /telegram/webhook")
    except Exception as e:
        print(f"Ошибка настройки вебхука: {str(e)}")

# Запускаем настройку вебхука при старте приложения
@app.on_event("startup")
async def startup_event():
    """Запускает настройку вебхука при старте приложения"""
    await setup_webhook()
    print("Приложение запущено. Используйте ручное тестирование через эндпоинт /telegram/webhook")

# Удаляем вебхук при завершении работы приложения
@app.on_event("shutdown")
async def shutdown_event():
    """Удаляет вебхук при завершении работы приложения"""
    try:
        # await bot.delete_webhook()
        print("Приложение остановлено")
    except Exception as e:
        print(f"Ошибка при удалении вебхука: {str(e)}")

# Задачи, выполняющиеся в фоновом режиме
async def send_notification(chat_id: str, message: str):
    """Отправляет уведомление в телеграм"""
    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Ошибка отправки уведомления: {str(e)}")

# Эндпоинты API
@app.get("/")
async def root():
    """Корневой эндпоинт для проверки работоспособности API"""
    return {"status": "ok", "message": "API работает"}

@app.get("/send_report")
async def send_report(background_tasks: BackgroundTasks):
    """Отправляет отчёт в телеграм"""
    background_tasks.add_task(send_notification, CHAT_ID, "Отчёт готов!")
    return {"message": "Уведомление отправлено"}

@app.post("/api/tokens")
async def save_tokens(tokens: ApiTokens, request: Request):
    """Сохраняет токены API для пользователя"""
    # Генерируем API ключ для пользователя (в реальном приложении это должно быть сложнее)
    api_key = f"user-{datetime.now().timestamp()}"
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Шифруем и сохраняем токены
    encrypted_tokens = encrypt_tokens(tokens.dict())
    users_db[user_hash] = {
        "tokens": encrypted_tokens,
        "created_at": datetime.now().isoformat(),
        "api_key": api_key
    }
    
    return {"api_key": api_key, "message": "Токены успешно сохранены"}

@app.delete("/api/tokens")
async def delete_tokens(api_key: str = Depends(api_key_header)):
    """Удаляет токены API пользователя"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash in users_db:
        del users_db[user_hash]
        return {"message": "Токены успешно удалены"}
    raise HTTPException(status_code=404, detail="Пользователь не найден")

@app.get("/products")
async def get_products(period: str = "month", api_key: Optional[str] = None, telegram_id: Optional[int] = None):
    """Получает список товаров с опциональной фильтрацией по периоду"""
    # Если передан telegram_id, получаем токены из базы данных
    if telegram_id:
        user_token = get_user_token(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        # TODO: Здесь добавить логику запроса к API Ozon с полученными токенами
        # В реальном проекте вместо mock_data будет использоваться API Ozon
    
    # Заглушка для тестирования
    mock_data = {
        "result": {
            "items": [
                {
                    "product_id": 123456,
                    "name": "Тестовый товар 1",
                    "offer_id": "TEST-001",
                    "price": 1500,
                    "images": ["https://via.placeholder.com/150"]
                },
                {
                    "product_id": 123457,
                    "name": "Тестовый товар 2",
                    "offer_id": "TEST-002",
                    "price": 2500,
                    "images": ["https://via.placeholder.com/150"]
                },
                {
                    "product_id": 123458,
                    "name": "Тестовый товар 3",
                    "offer_id": "TEST-003",
                    "price": 3500,
                    "images": ["https://via.placeholder.com/150"]
                }
            ]
        }
    }
    
    return mock_data

@app.post("/products/costs")
async def save_product_costs(costs: List[ProductCost], api_key: str = Depends(api_key_header)):
    """Сохраняет себестоимость товаров"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # В реальном приложении сохранять в БД
    users_db[user_hash]["product_costs"] = [cost.dict() for cost in costs]
    
    return {"message": "Себестоимость товаров сохранена"}

@app.get("/products/costs")
async def get_product_costs(api_key: str = Depends(api_key_header)):
    """Получает сохраненную себестоимость товаров"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    product_costs = users_db[user_hash].get("product_costs", [])
    return {"costs": product_costs}

@app.post("/notifications/settings")
async def save_notification_settings(settings: NotificationSettings, api_key: str = Depends(api_key_header)):
    """Сохраняет настройки уведомлений"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    users_db[user_hash]["notification_settings"] = settings.dict()
    
    return {"message": "Настройки уведомлений сохранены"}

@app.get("/analytics")
async def get_analytics(period: str = "month", api_key: Optional[str] = None, telegram_id: Optional[int] = None):
    """Получает аналитику по товарам за период"""
    # Если передан telegram_id, получаем токены из базы данных
    if telegram_id:
        user_token = get_user_token(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        # TODO: Здесь добавить логику запроса к API Ozon с полученными токенами
        # В реальном проекте вместо mock_analytics будет использоваться API Ozon
    
    # В реальном приложении здесь будет аналитика на основе данных Ozon API
    
    mock_analytics = {
        "period": period,
        "sales": 24500,
        "margin": 23.5,
        "roi": 42.8,
        "profit": 8250,
        "total_products": 36,
        "active_products": 28,
        "orders": 52,
        "average_order": 3100,
        "marketplace_fees": 3675,
        "advertising_costs": 2200,
        "sales_data": [15000, 18000, 22000, 24500, 20000, 23000, 24500],
        "margin_data": [18.5, 20.2, 22.8, 24.1, 23.5, 24.0, 23.5],
        "roi_data": [33.2, 38.5, 41.2, 43.7, 42.1, 42.5, 42.8]
    }
    
    return mock_analytics

# Функции для работы с API Ozon

async def get_ozon_products(api_token: str, client_id: str):
    """Получает список товаров из API Ozon"""
    try:
        url = "https://api-seller.ozon.ru/v2/product/list"
        
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_token,
            "Content-Type": "application/json"
        }
        
        # Получаем первую страницу товаров
        payload = {
            "filter": {
                "visibility": "ALL"
            },
            "last_id": "",
            "limit": 100
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            return None, f"Ошибка при получении товаров: {response.status_code} - {response.text}"
        
        data = response.json()
        return data, "Товары успешно получены"
    
    except Exception as e:
        return None, f"Ошибка при получении товаров: {str(e)}"

async def get_ozon_analytics(api_token: str, client_id: str, period: str = "month"):
    """Получает аналитику из API Ozon"""
    try:
        # Определяем даты для запроса в зависимости от периода
        end_date = datetime.now()
        
        if period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "year":
            start_date = end_date - timedelta(days=365)
        else:  # По умолчанию месяц
            start_date = end_date - timedelta(days=30)
        
        # Форматируем даты для API запроса
        date_from = start_date.strftime("%Y-%m-%d")
        date_to = end_date.strftime("%Y-%m-%d")
        
        # URL для запроса аналитики
        url = "https://api-seller.ozon.ru/v1/analytics/dashboard/comments"
        
        # Заголовки запроса
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_token,
            "Content-Type": "application/json"
        }
        
        # Тело запроса
        payload = {
            "date_from": date_from,
            "date_to": date_to,
            "metrics": ["comments_count", "negative_comments_count", "rating"],
            "dimension": ["sku"]
        }
        
        # Отправляем запрос
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            return None, f"Ошибка при получении аналитики: {response.status_code} - {response.text}"
        
        data = response.json()
        return data, "Аналитика успешно получена"
    
    except Exception as e:
        return None, f"Ошибка при получении аналитики: {str(e)}"

async def get_ozon_financial_data(api_token: str, client_id: str, period: str = "month"):
    """Получает финансовые данные из API Ozon"""
    try:
        # Определяем даты для запроса в зависимости от периода
        end_date = datetime.now()
        
        if period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "year":
            start_date = end_date - timedelta(days=365)
        else:  # По умолчанию месяц
            start_date = end_date - timedelta(days=30)
        
        # Форматируем даты для API запроса
        date_from = start_date.strftime("%Y-%m-%d")
        date_to = end_date.strftime("%Y-%m-%d")
        
        # URL для запроса финансовых данных
        url = "https://api-seller.ozon.ru/v1/finance/treasury/totals"
        
        # Заголовки запроса
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_token,
            "Content-Type": "application/json"
        }
        
        # Тело запроса
        payload = {
            "date_from": date_from,
            "date_to": date_to
        }
        
        # Отправляем запрос
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            return None, f"Ошибка при получении финансовых данных: {response.status_code} - {response.text}"
        
        data = response.json()
        return data, "Финансовые данные успешно получены"
    
    except Exception as e:
        return None, f"Ошибка при получении финансовых данных: {str(e)}"

# Обновляем API эндпоинты для работы с данными Ozon

@app.get("/api/products")
async def api_get_products(period: str = "month", telegram_id: Optional[int] = None, api_key: Optional[str] = None):
    """API для получения списка товаров"""
    # Проверяем и получаем токены
    ozon_api_token = None
    ozon_client_id = None
    
    if telegram_id:
        # Если передан telegram_id, получаем токены из базы данных
        user_token = get_user_token(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        ozon_api_token = user_token.ozon_api_token
        ozon_client_id = user_token.ozon_client_id
        
        # Обновляем время последнего использования
        update_token_usage(telegram_id)
    
    elif api_key:
        # Если передан api_key, получаем токены из хранилища
        try:
            user_hash = hashlib.sha256(api_key.encode()).hexdigest()
            if user_hash not in users_db:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            encrypted_tokens = users_db[user_hash]["tokens"]
            tokens = decrypt_tokens(encrypted_tokens)
            
            ozon_api_token = tokens.get("ozon_api_token")
            ozon_client_id = tokens.get("ozon_client_id")
            
            # Если есть telegram_id в токенах, обновляем время использования
            if "telegram_id" in tokens:
                update_token_usage(tokens["telegram_id"])
        
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Ошибка аутентификации: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail="Необходимо указать telegram_id или api_key")
    
    # Проверяем наличие токенов
    if not ozon_api_token or not ozon_client_id:
        raise HTTPException(status_code=400, detail="Токены Ozon не найдены")
    
    # Получаем данные из API Ozon
    data, message = await get_ozon_products(ozon_api_token, ozon_client_id)
    
    if not data:
        raise HTTPException(status_code=500, detail=message)
    
    return data

@app.get("/api/analytics")
async def api_get_analytics(period: str = "month", telegram_id: Optional[int] = None, api_key: Optional[str] = None):
    """API для получения аналитики"""
    # Проверяем и получаем токены
    ozon_api_token = None
    ozon_client_id = None
    
    if telegram_id:
        # Если передан telegram_id, получаем токены из базы данных
        user_token = get_user_token(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        ozon_api_token = user_token.ozon_api_token
        ozon_client_id = user_token.ozon_client_id
        
        # Обновляем время последнего использования
        update_token_usage(telegram_id)
    
    elif api_key:
        # Если передан api_key, получаем токены из хранилища
        try:
            user_hash = hashlib.sha256(api_key.encode()).hexdigest()
            if user_hash not in users_db:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            encrypted_tokens = users_db[user_hash]["tokens"]
            tokens = decrypt_tokens(encrypted_tokens)
            
            ozon_api_token = tokens.get("ozon_api_token")
            ozon_client_id = tokens.get("ozon_client_id")
            
            # Если есть telegram_id в токенах, обновляем время использования
            if "telegram_id" in tokens:
                update_token_usage(tokens["telegram_id"])
        
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Ошибка аутентификации: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail="Необходимо указать telegram_id или api_key")
    
    # Проверяем наличие токенов
    if not ozon_api_token or not ozon_client_id:
        raise HTTPException(status_code=400, detail="Токены Ozon не найдены")
    
    # Получаем данные аналитики
    analytics_data, analytics_message = await get_ozon_analytics(ozon_api_token, ozon_client_id, period)
    financial_data, financial_message = await get_ozon_financial_data(ozon_api_token, ozon_client_id, period)
    
    # Если не удалось получить данные, используем заглушки с сообщением об ошибке
    if not analytics_data:
        # Заглушка для тестирования с сообщением об ошибке
        mock_analytics = {
            "error": True,
            "message": analytics_message,
            "period": period,
            "sales": 24500,
            "margin": 23.5,
            "roi": 42.8,
            "profit": 8250,
            "total_products": 36,
            "active_products": 28,
            "orders": 52,
            "average_order": 3100,
            "marketplace_fees": 3675,
            "advertising_costs": 2200,
            "sales_data": [15000, 18000, 22000, 24500, 20000, 23000, 24500],
            "margin_data": [18.5, 20.2, 22.8, 24.1, 23.5, 24.0, 23.5],
            "roi_data": [33.2, 38.5, 41.2, 43.7, 42.1, 42.5, 42.8]
        }
        return mock_analytics
    
    # В реальном приложении здесь нужно обработать полученные данные и вернуть в нужном формате
    
    # Комбинируем данные из разных источников и возвращаем результат
    combined_data = {
        "success": True,
        "period": period,
        "analytics": analytics_data,
        "financial": financial_data if financial_data else {"error": financial_message}
    }
    
    return combined_data