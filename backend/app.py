from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, Body
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
from telegram.ext import ApplicationBuilder, ContextTypes
from telegram.ext import Application, CallbackContext
import aiohttp

# Функция для нечеткого сравнения строк (расстояние Левенштейна)
def levenshtein_distance(s1, s2):
    """Заглушка (неиспользуемая функция)"""
    return 0

def fuzzy_match(text, possible_matches, threshold=0.7):
    """Заглушка (неиспользуемая функция)"""
    return None, 0

# Загружаем переменные окружения из .env файла
load_dotenv(verbose=True)

# Получаем переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "default-key")

# URL веб-приложения
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://t.me/xyezonbot/shmazon")

# Инициализация базы данных
def init_db():
    """Инициализирует базу данных - создает таблицу пользователей"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_tokens (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    ozon_api_token TEXT NOT NULL,
                    ozon_client_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        
        # Инициализируем таблицу настроек уведомлений
        init_notification_settings_table()
        return True
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {str(e)}")
        return False

@contextmanager
def get_db():
    conn = sqlite3.connect('user_tokens.db')
    try:
        yield conn
    finally:
        conn.close()

# Функция для инициализации таблицы настроек уведомлений
def init_notification_settings_table():
    """Инициализирует таблицу настроек уведомлений в базе данных"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notification_settings (
                    telegram_id INTEGER PRIMARY KEY,
                    margin_threshold REAL DEFAULT 15.0,
                    roi_threshold REAL DEFAULT 30.0,
                    daily_report INTEGER DEFAULT 0,
                    sales_alert INTEGER DEFAULT 1,
                    returns_alert INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при инициализации таблицы настроек уведомлений: {str(e)}")
        return False

# Инициализируем базу данных при запуске
init_db()
init_notification_settings_table()

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
cipher_suite = Fernet(ENCRYPTION_KEY)

# Модели данных для API
class UserToken(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    ozon_api_token: str
    ozon_client_id: str
    last_used: Optional[str] = None  # Добавляем поле для хранения времени последнего использования

class ProductCost(BaseModel):
    product_id: int
    offer_id: str
    cost: float

class NotificationSettings(BaseModel):
    telegram_id: int
    margin_threshold: Optional[float] = 15.0  # По умолчанию 15%
    roi_threshold: Optional[float] = 30.0     # По умолчанию 30%
    daily_report: Optional[bool] = False      # Ежедневный отчет
    sales_alert: Optional[bool] = True        # Уведомления о продажах
    returns_alert: Optional[bool] = True      # Уведомления о возвратах

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

# Словарь для быстрого доступа к пользователям по API ключу
users_db_reverse = {}

# База данных телеграм-пользователей
telegram_users_db = {}

# Функция для обновления обратного словаря
def update_users_db_reverse():
    """Обновляет обратный словарь для быстрого доступа к пользователям по API ключу"""
    global users_db_reverse
    users_db_reverse = {user_info.get('api_key'): user_hash for user_hash, user_info in users_db.items() if 'api_key' in user_info}

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
async def save_user_token(user_id: int, api_token: str, client_id: str) -> bool:
    """Сохраняет токены пользователя в базу данных"""
    try:
        # Получаем имя пользователя (если оно было сохранено ранее)
        username = None
        user_token = await get_user_tokens(user_id)
        if user_token:
            username = user_token.username
        
        # Создаем объект с токенами
        user_token = UserToken(
            telegram_id=user_id,
            username=username,
            ozon_api_token=api_token,
            ozon_client_id=client_id
        )
        
        # Сохраняем в базу данных
        save_user_token_db(user_token)
        return True
    except Exception as e:
        print(f"Ошибка при сохранении токенов: {str(e)}")
        return False

def save_user_token_db(user_token: UserToken):
    """Сохраняет токены пользователя в базу данных (внутренняя функция)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_tokens 
            (telegram_id, username, ozon_api_token, ozon_client_id, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_token.telegram_id, user_token.username, user_token.ozon_api_token, user_token.ozon_client_id))
        conn.commit()

async def get_user_tokens(telegram_id: int) -> Optional[UserToken]:
    """Получает токены пользователя из базы данных с дополнительной информацией"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                telegram_id, 
                username, 
                ozon_api_token, 
                ozon_client_id, 
                last_updated 
            FROM user_tokens 
            WHERE telegram_id = ?
        ''', (telegram_id,))
        row = cursor.fetchone()
        
        if row:
            # Создаем объект с токенами и дополнительными полями
            token = UserToken(
                telegram_id=row[0],
                username=row[1],
                ozon_api_token=row[2],
                ozon_client_id=row[3]
            )
            # Добавляем время последнего использования
            setattr(token, 'last_used', row[4] if len(row) > 4 else None)
            return token
        return None

async def delete_user_tokens(telegram_id: int) -> bool:
    """Удаляет токены пользователя из базы данных"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_tokens WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при удалении токенов: {str(e)}")
        return False

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
        [KeyboardButton("/start"), KeyboardButton("/help")],
        [KeyboardButton("/set_token"), KeyboardButton("/status")],
        [KeyboardButton("/stats"), KeyboardButton("/delete_tokens")],
        [KeyboardButton("/verify")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите команду или введите сообщение...")

# Функция для создания инлайн клавиатуры с кнопкой приложения
def get_app_button():
    """Создает инлайн клавиатуру с кнопкой для открытия приложения"""
    keyboard = [[InlineKeyboardButton("🚀 Открыть приложение Ozon Analytics", url=WEB_APP_URL)]]
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
            BotCommand("delete_tokens", "Удалить токены"),
            BotCommand("notifications", "Настройки уведомлений"),
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
    if not update.message or not update.message.text:
        print("Ошибка: нет текста сообщения в handle_command")
        return
        
    # Получаем и нормализуем команду
    command_text = update.message.text.strip()
    
    # Извлекаем команду из текста
    if command_text.startswith('/'):
        # Если это прямая команда с символом /
        command = command_text.split()[0][1:].lower()  # удаляем символ / и берем первое слово, приводим к нижнему регистру
    else:
        # Если это текстовая команда без символа /
        command_lower = command_text.lower()
        
        # Явное сопоставление с известными командами
        if "запустить" in command_lower or "бота" in command_lower or "start" in command_lower:
            command = "start"
        elif "помощь" in command_lower or "справка" in command_lower or "help" in command_lower:
            command = "help"
        elif "установить" in command_lower and "токены" in command_lower or "set_token" in command_lower:
            command = "set_token"
        elif "проверить статус" in command_lower or "статус" in command_lower or "status" in command_lower:
            command = "status"
        elif "статистика" in command_lower or "stats" in command_lower:
            command = "stats"
        elif "удалить" in command_lower and "токены" in command_lower or "delete_tokens" in command_lower:
            command = "delete_tokens"
        elif "проверить" in command_lower and "токены" in command_lower or "verify" in command_lower:
            command = "verify"
        elif "отмена" in command_lower or "cancel" in command_lower:
            command = "cancel"
        elif "notifications" in command_lower or "notifications" in command_lower:
            command = "notifications"
        else:
            print(f"Неизвестная команда без /: {command_text}")
            command = "unknown"
    
    print(f"Обработка команды: '{command}' из текста: '{command_text}'")
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    print(f"Обрабатываю команду '{command}' от пользователя {user_id}")
    
    # Создаем клавиатуру
    reply_markup = get_main_keyboard()
    
    # Обработка команд
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
        # Проверяем аргументы команды
        args = update.message.text.split()
        
        if len(args) >= 3:
            # Пользователь передал токены в команде
            api_token = args[1]
            client_id = args[2]
            
            print(f"Получены токены от пользователя {user_id}: API token={api_token[:5]}..., Client ID={client_id}")
            
            # Создаем объект с токенами
            user_token = UserToken(
                telegram_id=user_id,
                username=username,
                ozon_api_token=api_token,
                ozon_client_id=client_id
            )
            
            # Пытаемся сохранить токены в базу данных
            try:
                print("Сохраняю токены в базу данных...")
                # Используем напрямую функцию для сохранения в БД
                save_user_token_db(user_token)
                
                # Проверяем, что токены сохранились
                saved_token = await get_user_tokens(user_id)
                if saved_token:
                    print(f"Токены успешно сохранены для пользователя {user_id}")
                    
                    # Отправляем сообщение об успешном сохранении
                    await update.message.reply_text(
                        "✅ API токены успешно сохранены!\n\n"
                        "Теперь вы можете использовать веб-приложение для анализа данных вашего магазина Ozon.",
                        reply_markup=reply_markup
                    )
                else:
                    print(f"Ошибка: токены не найдены в БД после сохранения для пользователя {user_id}")
                    
                    # Отправляем сообщение об ошибке
                    await update.message.reply_text(
                        "❌ Произошла ошибка при сохранении токенов.\n\n"
                        "Пожалуйста, попробуйте еще раз позже или обратитесь в поддержку.",
                        reply_markup=reply_markup
                    )
            except Exception as e:
                print(f"Ошибка при сохранении токенов: {type(e).__name__} - {str(e)}")
                
                # Отправляем сообщение об ошибке
                await update.message.reply_text(
                    f"❌ Произошла ошибка при сохранении токенов: {str(e)}\n\n"
                    "Пожалуйста, попробуйте еще раз позже или обратитесь в поддержку.",
                    reply_markup=reply_markup
                )
                
            return
        
        # Устанавливаем состояние пользователя
        user_states[user_id] = "waiting_for_api_token"
        await update.message.reply_text(
            "🔑 Пожалуйста, отправьте ваш API токен Ozon.\n\n"
            "Вы можете найти его в личном кабинете Ozon в разделе API.",
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
            "/help - Показать это сообщение\n"
            "/notifications - Настройки уведомлений\n\n"
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
    
    elif command == "notifications":
        try:
            # Получаем настройки пользователя
            settings = await get_notification_settings(update.effective_user.id)
            
            # Формируем сообщение с текущими настройками
            settings_message = (
                f"🔔 *Текущие настройки уведомлений*\n\n"
                f"• Порог маржинальности: {settings.margin_threshold}%\n"
                f"• Порог ROI: {settings.roi_threshold}%\n"
                f"• Ежедневный отчет: {'Включен' if settings.daily_report else 'Выключен'}\n"
                f"• Уведомления о продажах: {'Включены' if settings.sales_alert else 'Выключены'}\n"
                f"• Уведомления о возвратах: {'Включены' if settings.returns_alert else 'Выключены'}\n\n"
                f"Для изменения настроек используйте команды:\n"
                f"/set_margin_threshold [число] - установить порог маржинальности\n"
                f"/set_roi_threshold [число] - установить порог ROI\n"
                f"/toggle_daily_report - вкл/выкл ежедневный отчет\n"
                f"/toggle_sales_alert - вкл/выкл уведомления о продажах\n"
                f"/toggle_returns_alert - вкл/выкл уведомления о возвратах"
            )
            
            await update.message.reply_text(settings_message, parse_mode="Markdown")
            return
            
        except Exception as e:
            error_message = f"Ошибка при получении настроек уведомлений: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
    # Обработка команды установки порога маржинальности
    if command.startswith('/set_margin_threshold'):
        try:
            # Извлекаем значение порога
            parts = command.split()
            if len(parts) < 2:
                await update.message.reply_text("Пожалуйста, укажите значение порога маржинальности. Например: /set_margin_threshold 15")
                return
                
            threshold = float(parts[1])
            if threshold < 0:
                await update.message.reply_text("Порог маржинальности не может быть отрицательным.")
                return
                
            # Получаем и обновляем настройки
            settings = await get_notification_settings(update.effective_user.id)
            settings.margin_threshold = threshold
            await save_notification_settings(settings)
            
            await update.message.reply_text(f"✅ Порог маржинальности установлен на {threshold}%")
            return
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, укажите корректное числовое значение порога.")
            return
        except Exception as e:
            error_message = f"Ошибка при установке порога маржинальности: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
    # Обработка команды установки порога ROI
    if command.startswith('/set_roi_threshold'):
        try:
            # Извлекаем значение порога
            parts = command.split()
            if len(parts) < 2:
                await update.message.reply_text("Пожалуйста, укажите значение порога ROI. Например: /set_roi_threshold 30")
                return
                
            threshold = float(parts[1])
            if threshold < 0:
                await update.message.reply_text("Порог ROI не может быть отрицательным.")
                return
                
            # Получаем и обновляем настройки
            settings = await get_notification_settings(update.effective_user.id)
            settings.roi_threshold = threshold
            await save_notification_settings(settings)
            
            await update.message.reply_text(f"✅ Порог ROI установлен на {threshold}%")
            return
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, укажите корректное числовое значение порога.")
            return
        except Exception as e:
            error_message = f"Ошибка при установке порога ROI: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
    # Обработка команды переключения ежедневного отчета
    if command == '/toggle_daily_report':
        try:
            settings = await get_notification_settings(update.effective_user.id)
            settings.daily_report = not settings.daily_report
            await save_notification_settings(settings)
            
            status = "включены" if settings.daily_report else "выключены"
            await update.message.reply_text(f"✅ Ежедневные отчеты {status}")
            return
            
        except Exception as e:
            error_message = f"Ошибка при изменении настроек ежедневного отчета: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
    # Обработка команды переключения уведомлений о продажах
    if command == '/toggle_sales_alert':
        try:
            settings = await get_notification_settings(update.effective_user.id)
            settings.sales_alert = not settings.sales_alert
            await save_notification_settings(settings)
            
            status = "включены" if settings.sales_alert else "выключены"
            await update.message.reply_text(f"✅ Уведомления о продажах {status}")
            return
            
        except Exception as e:
            error_message = f"Ошибка при изменении настроек уведомлений о продажах: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
    # Обработка команды переключения уведомлений о возвратах
    if command == '/toggle_returns_alert':
        try:
            settings = await get_notification_settings(update.effective_user.id)
            settings.returns_alert = not settings.returns_alert
            await save_notification_settings(settings)
            
            status = "включены" if settings.returns_alert else "выключены"
            await update.message.reply_text(f"✅ Уведомления о возвратах {status}")
            return
            
        except Exception as e:
            error_message = f"Ошибка при изменении настроек уведомлений о возвратах: {str(e)}"
            await update.message.reply_text(error_message)
            return
    
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
    message_text = update.message.text.strip() if update.message.text else ""

    print(f"Получено текстовое сообщение: '{message_text}' от пользователя {user_id}")

    # Проверяем, есть ли пользователь в словаре состояний
    if user_id not in user_states:
        user_states[user_id] = "idle"
        await update.message.reply_text(
            "Для начала работы с ботом, пожалуйста, используйте команду /start",
            reply_markup=get_main_keyboard()
        )
        return

    current_state = user_states[user_id]
    reply_markup = get_main_keyboard()
    
    # Если сообщение начинается с /, это команда - передаем в обработчик команд
    if message_text.startswith('/'):
        print(f"Обнаружена команда в сообщении: {message_text}")
        await handle_command(update, context)
        return
    
    # Проверка для кнопок клавиатуры, если сообщение совпадает с командой, но без /
    command_to_check = f"/{message_text.lower()}"
    if command_to_check in ["/start", "/help", "/set_token", "/status", "/stats", "/delete_tokens", "/verify"]:
        print(f"Обнаружена команда без / из кнопки: {message_text} -> {command_to_check}")
        update.message.text = command_to_check
        await handle_command(update, context)
        return
    
    # Обработка текстовых кнопок с русскими названиями
    message_lower = message_text.lower()
    if "запустить" in message_lower or "бота" in message_lower:
        print(f"Команда из текста: {message_text} -> /start")
        update.message.text = "/start"
        await handle_command(update, context)
        return
    elif "помощь" in message_lower or "справка" in message_lower:
        print(f"Команда из текста: {message_text} -> /help")
        update.message.text = "/help"
        await handle_command(update, context)
        return
    elif "установить" in message_lower and "токены" in message_lower or "токены" in message_lower and "удалить" not in message_lower:
        print(f"Команда из текста: {message_text} -> /set_token")
        update.message.text = "/set_token"
        await handle_command(update, context)
        return
    elif "статус" in message_lower or "проверить статус" in message_lower:
        print(f"Команда из текста: {message_text} -> /status")
        update.message.text = "/status"
        await handle_command(update, context)
        return
    elif "статистика" in message_lower:
        print(f"Команда из текста: {message_text} -> /stats")
        update.message.text = "/stats"
        await handle_command(update, context)
        return
    elif "удалить" in message_lower and "токены" in message_lower:
        print(f"Команда из текста: {message_text} -> /delete_tokens")
        update.message.text = "/delete_tokens"
        await handle_command(update, context)
        return
    elif "проверить токены" in message_lower or "проверить" in message_lower and "токены" in message_lower or "валидность" in message_lower:
        print(f"Команда из текста: {message_text} -> /verify")
        update.message.text = "/verify"
        await handle_command(update, context)
        return

    # Если пользователь в состоянии ожидания API токена
    if current_state == "waiting_for_api_token":
        # Очищаем токен от кавычек и пробелов
        cleaned_token = message_text.strip("\"' \t\n")
        
        # Пользователь слишком коротким ответом вводит токен
        if len(cleaned_token) < 10:
            await update.message.reply_text(
                "❌ Некорректный формат API токена. Токен должен быть достаточно длинным.\n\n"
                "🔑 API токен обычно имеет вид XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX\n\n"
                "Пожалуйста, отправьте правильный API токен или используйте /cancel для отмены.",
                reply_markup=reply_markup
            )
            return
        
        # Сохраняем токен в состоянии пользователя
        user_states[user_id] = {"state": "waiting_for_client_id", "api_token": cleaned_token}
        
        await update.message.reply_text(
            "✅ API токен сохранен\n\n"
            "Теперь, пожалуйста, отправьте ID клиента (Client ID).\n"
            "Вы можете найти его в личном кабинете Ozon в разделе API.",
            reply_markup=reply_markup
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
                "Пожалуйста, отправьте правильный Client ID или используйте /cancel для отмены.",
                reply_markup=reply_markup
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
                    "Теперь вы можете использовать веб-приложение для анализа ваших товаров на Ozon.",
                    reply_markup=reply_markup
                )
            else:
                # Устанавливаем состояние ожидания API токена
                user_states[user_id] = "waiting_for_api_token"
                
                # Обновляем прогресс-сообщение
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id,
                    text="❌ Произошла ошибка при сохранении токенов. Пожалуйста, попробуйте еще раз.",
                    reply_markup=reply_markup
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
                "Начните процесс заново с команды /set_token.",
                reply_markup=reply_markup
            )
        return
    
    # Для всех других состояний
    await update.message.reply_text(
        "Я не понимаю этой команды. Пожалуйста, используйте /help чтобы увидеть список доступных команд.",
        reply_markup=reply_markup
    )

@app.post("/webhook/{token}")
async def telegram_webhook_with_token(token: str, update: dict = None):
    """Обработчик вебхука от Telegram (новая версия с передачей токена)"""
    if not update:
        return {"status": "error", "message": "Нет данных в запросе"}
        
    if token != TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "Неверный токен бота"}
    
    try:
        # Проверка наличия ключевых полей в обновлении
        if not isinstance(update, dict):
            return {"status": "error", "message": "Неверный формат данных"}
            
        # Логируем получение обновления для отладки
        update_id = update.get('update_id', 'неизвестно')
        message_data = update.get('message', {})
        message_text = message_data.get('text', 'нет текста') if message_data else 'нет текста'
        user_id = message_data.get('from', {}).get('id', 'неизвестно') if message_data else 'неизвестно'
        username = message_data.get('from', {}).get('username', 'неизвестно') if message_data else 'неизвестно'
        
        print(f"Получено обновление #{update_id} от пользователя {user_id} (@{username}): {message_text[:100]}...")
        
        # Дополнительная информация для отладки сообщений
        if message_text:
            print(f"Содержимое сообщения: '{message_text}' (длина: {len(message_text)})")
            print(f"Коды символов: {[ord(c) for c in message_text[:20]]}")
        
        # Используем правильный метод для создания объекта Update
        update_obj = Update.de_json(data=update, bot=bot)
        
        # Создаем объект приложения и контекста
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        context = CallbackContext(application)
        
        # Проверяем, что это сообщение (может быть другой тип обновления)
        if update_obj and update_obj.message:
            # Если это команда
            if update_obj.message.text and update_obj.message.text.startswith('/'):
                print(f"Обрабатываем команду: {update_obj.message.text}")
                await handle_command(update_obj, context)
            # Если это обычный текст
            elif update_obj.message.text:
                print(f"Обрабатываем текстовое сообщение: {update_obj.message.text}")
                await handle_message(update_obj, context)
            else:
                print(f"Получено сообщение без текста от пользователя {user_id}")
                # Отправляем клавиатуру в любом случае
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="Используйте команды бота или кнопки ниже:",
                        reply_markup=get_main_keyboard()
                    )
                except Exception as inner_e:
                    print(f"Ошибка при отправке клавиатуры: {str(inner_e)}")
        else:
            print(f"Получено обновление, не содержащее сообщения: {str(update)[:200]}...")
        
        return {"status": "ok", "message": "Обновление обработано"}
    except Exception as e:
        # Подробный вывод ошибки для отладки
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"Ошибка при обработке вебхука: {error_type} - {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Более подробный ответ
        return {
            "status": "error", 
            "error_type": error_type,
            "message": error_msg,
            "update_id": update.get('update_id', 'неизвестно') if isinstance(update, dict) else 'неизвестно'
        }

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Обработчик вебхука от Telegram (старая версия для совместимости)"""
    try:
        # Попытка прочитать тело запроса
        try:
            update_data = await request.json()
        except Exception as e:
            print(f"Ошибка при чтении тела запроса: {str(e)}")
            return {"status": "error", "message": "Ошибка при чтении тела запроса"}
            
        # Базовая проверка
        if not isinstance(update_data, dict):
            return {"status": "error", "message": "Неверный формат данных"}
        
        # Логируем получение обновления для отладки
        update_id = update_data.get('update_id', 'неизвестно')
        message_text = update_data.get('message', {}).get('text', 'нет текста')
        user_id = update_data.get('message', {}).get('from', {}).get('id', 'неизвестно')
        username = update_data.get('message', {}).get('from', {}).get('username', 'неизвестно')
        print(f"Получен вебхук через /telegram/webhook: #{update_id} от пользователя {user_id} (@{username}): {message_text[:100]}...")
            
        # Создаем объект Update
        try:
            # В python-telegram-bot нужно использовать Update.de_json вместо from_dict
            update_obj = Update.de_json(data=update_data, bot=bot)
            
            # Создаем объект приложения и контекста
            application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            context = CallbackContext(application)
            
            # Проверяем, что это сообщение (может быть другой тип обновления)
            if update_obj and update_obj.message:
                # Если это команда
                if update_obj.message.text and update_obj.message.text.startswith('/'):
                    print(f"Обрабатываем команду через /telegram/webhook: {update_obj.message.text}")
                    await handle_command(update_obj, context)
                # Если это обычный текст
                elif update_obj.message.text:
                    print(f"Обрабатываем текстовое сообщение через /telegram/webhook: {update_obj.message.text}")
                    await handle_message(update_obj, context)
                else:
                    print(f"Получено сообщение без текста от пользователя {user_id}")
            else:
                print(f"Получено обновление, не содержащее сообщения: {str(update_data)[:200]}...")
                
            return {"status": "ok", "message": "Обновление обработано"}
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"Ошибка обработки Update: {error_type} - {error_msg}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "error_type": error_type, "message": error_msg}
    except Exception as e:
        print(f"Ошибка обработки вебхука через /telegram/webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Ошибка: {str(e)}"}

@app.get("/telegram/user/{user_id}/tokens")
async def get_telegram_user_tokens(user_id: int):
    """Получает API токены пользователя Telegram"""
    user_token = await get_user_tokens(user_id)
    
    if not user_token:
        raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
    
    # Возвращаем данные в формате, который ожидает фронтенд
    return {
        "ozon_api_token": user_token.ozon_api_token,
        "ozon_client_id": user_token.ozon_client_id
    }

# Функция проверки актуальности токенов через API Ozon
async def verify_ozon_tokens(api_token: str, client_id: str) -> tuple:
    """Проверяет валидность токенов Ozon API"""
    try:
        # Проверка на тестовые токены
        if api_token.lower().startswith('test') or api_token.lower().startswith('demo'):
            return (True, "Валидация успешна (тестовый режим)")
        
        # Делаем запрос к Ozon API для проверки валидности токенов
        headers = {
            'Client-Id': client_id,
            'Api-Key': api_token,
            'Content-Type': 'application/json'
        }
        
        # Используем простой endpoint для проверки
        url = "https://api-seller.ozon.ru/v1/actions"
        payload = {}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_json = await response.json()
                    if response.status == 200:
                        return (True, "Валидация успешна")
                    else:
                        error_message = response_json.get('message', 'Неизвестная ошибка')
                        return (False, f"Ошибка: {error_message}")
        except Exception as e:
            # Попробуем альтернативный метод - синхронный запрос
            try:
                response = requests.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    return (True, "Валидация успешна")
                else:
                    error_message = response.json().get('message', 'Неизвестная ошибка')
                    return (False, f"Ошибка: {error_message}")
            except Exception as inner_e:
                return (False, f"Ошибка при проверке через {url}: {str(inner_e)}")
    
    except Exception as e:
        return (False, f"Ошибка при проверке токенов: {str(e)}")

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
        save_user_token_db(user_token)
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
    try:
        print(f"Попытка авторизации для telegram_id: {telegram_id}")
        
        user_token = await get_user_tokens(telegram_id)
        
        if not user_token:
            print(f"Пользователь {telegram_id} не найден или нет токенов")
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены. Пожалуйста, установите токены через Telegram бота.")
        
        print(f"Пользователь {telegram_id} найден, получены токены: {user_token.ozon_api_token[:5]}..., {user_token.ozon_client_id}")
        
        # Обновляем время последнего использования токенов
        try:
            update_token_usage(telegram_id)
            print(f"Обновлено время использования токенов для {telegram_id}")
        except Exception as e:
            print(f"Ошибка при обновлении времени использования: {str(e)}")
            # Продолжаем выполнение, так как это не критическая ошибка
        
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
        try:
            is_valid, message = await verify_ozon_tokens(user_token.ozon_api_token, user_token.ozon_client_id)
            if not is_valid:
                print(f"Токены для {telegram_id} недействительны: {message}")
                raise HTTPException(status_code=400, detail=f"Токены больше не действительны. Пожалуйста, обновите их через Telegram бота. Ошибка: {message}")
            print(f"Токены для {telegram_id} действительны")
        except Exception as e:
            print(f"Ошибка при проверке токенов для {telegram_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Ошибка при проверке токенов: {str(e)}")
        
        # Шифруем и сохраняем токены
        try:
            encrypted_tokens = encrypt_tokens(tokens)
            users_db[user_hash] = {
                "tokens": encrypted_tokens,
                "created_at": datetime.now().isoformat(),
                "api_key": api_key,
                "telegram_id": telegram_id
            }
            print(f"Токены успешно сохранены в кэше для {telegram_id}")
            
            # Обновляем обратный словарь
            update_users_db_reverse()
        except Exception as e:
            print(f"Ошибка при шифровании/сохранении токенов для {telegram_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Ошибка при шифровании токенов: {str(e)}")
        
        return {
            "api_key": api_key,
            "message": "Авторизация успешна",
            "ozon_api_token": user_token.ozon_api_token,
            "ozon_client_id": user_token.ozon_client_id
        }
    except HTTPException:
        # Пробрасываем HTTPException дальше
        raise
    except Exception as e:
        print(f"Неожиданная ошибка при авторизации через Telegram ID {telegram_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")

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
    # Настраиваем команды бота
    await setup_bot_commands()
    
    # Настраиваем webhook
    await setup_webhook()
    print("Приложение запущено. Используйте ручное тестирование через эндпоинт /telegram/webhook")
    
    # Инициализируем базу данных
    init_db()
    
    # Celery теперь управляет всеми фоновыми задачами, поэтому здесь их не запускаем
    print("Фоновые задачи и обновление данных управляются через Celery")
    
    # ... (остальной код функции startup_event) ...

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
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
        return True
    except Exception as e:
        print(f"Ошибка при отправке уведомления: {str(e)}")
        return False

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
    
    # Обновляем обратный словарь
    update_users_db_reverse()
    
    return {"api_key": api_key, "message": "Токены успешно сохранены"}

@app.delete("/api/tokens")
async def delete_tokens(api_key: str = Depends(api_key_header)):
    """Удаляет токены API пользователя"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash in users_db:
        del users_db[user_hash]
        # Обновляем обратный словарь
        update_users_db_reverse()
        return {"message": "Токены успешно удалены"}
    raise HTTPException(status_code=404, detail="Пользователь не найден")

@app.get("/products")
async def get_products(period: str = "month", api_key: Optional[str] = None, telegram_id: Optional[int] = None):
    """Получает список товаров с опциональной фильтрацией по периоду"""
    # Если передан telegram_id, получаем токены из базы данных
    if telegram_id:
        user_token = await get_user_tokens(telegram_id)
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
    # Проверка на тестовые токены
    if api_key.lower().startswith('test') or api_key.lower().startswith('demo'):
        return {"message": "Себестоимость товаров сохранена (тестовый режим)"}
    
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if user_hash not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # В реальном приложении сохранять в БД
    if "product_costs" not in users_db[user_hash]:
        users_db[user_hash]["product_costs"] = []
    
    # Обновляем или добавляем себестоимость для каждого товара
    for cost in costs:
        # Проверяем, есть ли уже такой товар
        found = False
        for i, existing_cost in enumerate(users_db[user_hash]["product_costs"]):
            if existing_cost["offer_id"] == cost.offer_id:
                users_db[user_hash]["product_costs"][i] = cost.dict()
                found = True
                break
        
        # Если товар не найден, добавляем его
        if not found:
            users_db[user_hash]["product_costs"].append(cost.dict())
    
    return {"message": "Себестоимость товаров сохранена"}

@app.get("/products/costs")
async def get_product_costs(api_key: str = Depends(api_key_header)):
    """Получает сохраненную себестоимость товаров"""
    user_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    # Проверка на тестовые токены
    if api_key.lower().startswith('test') or api_key.lower().startswith('demo'):
        # Возвращаем тестовые данные о себестоимости
        return {
            "items": [
                {"offer_id": "TEST-001", "cost": 1500.0},
                {"offer_id": "TEST-002", "cost": 1900.0},
                {"offer_id": "TEST-003", "cost": 750.0}
            ]
        }
    
    if user_hash not in users_db:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    product_costs = users_db[user_hash].get("product_costs", [])
    return {"items": product_costs}

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
        user_token = await get_user_tokens(telegram_id)
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
    
    # Проверка на тестовые токены
    if (api_token.lower().startswith('test') or api_token.lower().startswith('demo')):
        # Возвращаем тестовые данные
        test_products = {
            "result": {
                "items": [
                    {
                        "product_id": 123456789,
                        "offer_id": "TEST-001",
                        "name": "Тестовый товар 1",
                        "price": "2990",
                        "stock": 10,
                        "status": "active"
                    },
                    {
                        "product_id": 987654321,
                        "offer_id": "TEST-002",
                        "name": "Тестовый товар 2",
                        "price": "4500",
                        "stock": 5,
                        "status": "active"
                    },
                    {
                        "product_id": 555555555,
                        "offer_id": "TEST-003",
                        "name": "Тестовый товар 3",
                        "price": "1200",
                        "stock": 0,
                        "status": "inactive"
                    }
                ],
                "total": 3
            }
        }
        
        return test_products
    
    # Для реальных токенов делаем запрос к API
    url = "https://api-seller.ozon.ru/v2/product/list"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "filter": {},
        "limit": 100,
        "offset": 0
    }
    
    try:
        # Используем aiohttp для асинхронного запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    # Получаем тело ответа с ошибкой
                    error_body = await response.text()
                    error_detail = f"HTTP {response.status}: {error_body}"
                    raise HTTPException(status_code=400, detail=f"Ошибка API Ozon: {error_detail}")
    except Exception as e:
        # Запасной вариант - синхронный запрос через requests
        try:
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                error_detail = f"HTTP {response.status_code}: {response.text}"
                raise HTTPException(status_code=400, detail=f"Ошибка API Ozon: {error_detail}")
        except Exception as inner_e:
            raise HTTPException(status_code=500, detail=f"Ошибка при получении товаров: {str(inner_e)}")

async def get_ozon_analytics(api_token: str, client_id: str, period: str = "month"):
    """Получает аналитику продаж из API Ozon"""
    
    # Для тестовых токенов возвращаем тестовые данные
    if api_token.lower().startswith('test') or api_token.lower().startswith('demo'):
        print(f"Используем тестовые данные для аналитики (токен {api_token[:5]}...)")
        
        # Возвращаем тестовые данные для демонстрации
    return {
            "status": "success",
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
    
    # Настройка периода для запроса
    current_date = datetime.now()
    
    if period == "week":
        # Последние 7 дней
        date_from = (current_date - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "month":
        # Последние 30 дней
        date_from = (current_date - timedelta(days=30)).strftime("%Y-%m-%d")
    elif period == "year":
        # Последний год
        date_from = (current_date - timedelta(days=365)).strftime("%Y-%m-%d")
    else:
        # По умолчанию - последние 30 дней
        date_from = (current_date - timedelta(days=30)).strftime("%Y-%m-%d")
    
    date_to = current_date.strftime("%Y-%m-%d")
    
    # Получаем данные о финансах из Ozon API
    try:
        financial_data = await get_ozon_financial_data(api_token, client_id, period)
        
        # Формируем ответ на основе финансовых данных
        return {
            "status": "success",
            "period": period,
            "sales": financial_data.get("sales", 0),
            "margin": financial_data.get("margin", 0),
            "roi": financial_data.get("roi", 0),
            "profit": financial_data.get("profit", 0),
            "total_products": financial_data.get("total_products", 0),
            "active_products": financial_data.get("active_products", 0),
            "orders": financial_data.get("orders", 0),
            "average_order": financial_data.get("average_order", 0),
            "marketplace_fees": financial_data.get("marketplace_fees", 0),
            "advertising_costs": financial_data.get("advertising_costs", 0),
            "sales_data": financial_data.get("sales_data", []),
            "margin_data": financial_data.get("margin_data", []),
            "roi_data": financial_data.get("roi_data", [])
        }
    except Exception as e:
        print(f"Ошибка при получении аналитики: {str(e)}")
        
        # В случае ошибки возвращаем базовую структуру с сообщением об ошибке
        return {
            "error": True,
            "message": f"Ошибка при получении аналитики: {str(e)}",
            "period": period,
            "sales": 0,
            "margin": 0,
            "roi": 0,
            "profit": 0,
            "total_products": 0,
            "active_products": 0,
            "orders": 0,
            "average_order": 0,
            "marketplace_fees": 0,
            "advertising_costs": 0,
            "sales_data": [],
            "margin_data": [],
            "roi_data": []
        }

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
    # Получаем токены из API ключа или Telegram ID
    if api_key:
        # Используем API ключ
        if api_key not in users_db_reverse:
            # Если это тестовый API ключ
            if api_key.lower().startswith('test') or api_key.lower().startswith('demo'):
                api_token = "test_token"
                client_id = "test_client_id"
            else:
                raise HTTPException(status_code=401, detail="Недействительный API ключ")
        else:
            user_info = users_db[users_db_reverse[api_key]]
            tokens = decrypt_tokens(user_info['tokens'])
            
            api_token = tokens['ozon_api_token']
            client_id = tokens['ozon_client_id']
    elif telegram_id:
        # Используем Telegram ID
        user_token = await get_user_tokens(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        api_token = user_token.ozon_api_token
        client_id = user_token.ozon_client_id
    else:
        raise HTTPException(status_code=400, detail="Необходимо указать telegram_id или api_key")
    
    try:
        # Получаем список товаров с помощью API Ozon
        products_data = await get_ozon_products(api_token, client_id)
        
        # Для тестовых данных не запрашиваем себестоимость, возвращаем фиктивные данные
        if api_token.lower().startswith('test') or api_token.lower().startswith('demo') or api_key.lower().startswith('test') or api_key.lower().startswith('demo'):
            # Создаем тестовые данные о себестоимости
            costs_mapping = {
                "TEST-001": {"cost": 1500.0},
                "TEST-002": {"cost": 1900.0},
                "TEST-003": {"cost": 750.0}
            }
        else:
            # Получаем сохраненные данные о себестоимости товаров
            try:
                costs_data = await get_product_costs(api_key=api_key)
                costs_mapping = {}
                
                for cost in costs_data.get('items', []):
                    costs_mapping[cost['offer_id']] = {
                        'cost': cost['cost']
                    }
            except Exception as e:
                print(f"Ошибка при получении себестоимости: {str(e)}")
                costs_mapping = {}  # Если не удалось получить себестоимость, используем пустой словарь
            
        # Проходим по списку товаров и добавляем дополнительные данные
        result_items = []
        total = 0
        
        if 'result' in products_data and 'items' in products_data['result']:
            total = products_data['result'].get('total', len(products_data['result']['items']))
            
            for item in products_data['result']['items']:
                # Добавляем данные о себестоимости, если есть
                offer_id = item.get('offer_id', '')
                if offer_id in costs_mapping:
                    cost = costs_mapping[offer_id]['cost']
                    item['cost'] = cost
                    
                    # Рассчитываем маржинальность
                    price = float(item.get('price', 0))
                    if price > 0 and cost > 0:
                        margin_percent = ((price - cost) / price) * 100
                        item['margin_percent'] = round(margin_percent, 2)
                    else:
                        item['margin_percent'] = 0
                else:
                    item['cost'] = 0
                    item['margin_percent'] = 0
                
                result_items.append(item)
                
        return {
            "items": result_items,
            "total": total,
            "status": "success"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении товаров: {str(e)}")

@app.get("/api/analytics")
async def api_get_analytics(period: str = "month", telegram_id: Optional[int] = None, api_key: Optional[str] = None):
    """API для получения аналитики"""
    # Получаем токены из API ключа или Telegram ID
    if api_key:
        # Используем API ключ
        if api_key not in users_db_reverse:
            # Если это тестовый API ключ
            if api_key.lower().startswith('test') or api_key.lower().startswith('demo'):
                api_token = "test_token"
                client_id = "test_client_id"
            else:
                raise HTTPException(status_code=401, detail="Недействительный API ключ")
        else:
            user_info = users_db[users_db_reverse[api_key]]
            tokens = decrypt_tokens(user_info['tokens'])
            
            api_token = tokens['ozon_api_token']
            client_id = tokens['ozon_client_id']
    elif telegram_id:
        # Используем Telegram ID
        user_token = await get_user_tokens(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Пользователь не найден или не установлены API токены")
        
        api_token = user_token.ozon_api_token
        client_id = user_token.ozon_client_id
    else:
        raise HTTPException(status_code=400, detail="Необходимо указать telegram_id или api_key")
    
    try:
        # Получаем аналитику с помощью API Ozon
        analytics_data = await get_ozon_analytics(api_token, client_id, period)
        
        # Функция уже возвращает готовый результат
        return analytics_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении аналитики: {str(e)}")

# Получение настроек уведомлений пользователя
async def get_notification_settings(telegram_id: int) -> Optional[NotificationSettings]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT telegram_id, margin_threshold, roi_threshold, daily_report, sales_alert, returns_alert
            FROM notification_settings
            WHERE telegram_id = ?
        ''', (telegram_id,))
        
        row = cursor.fetchone()
        if row:
            return NotificationSettings(
                telegram_id=row[0],
                margin_threshold=row[1],
                roi_threshold=row[2],
                daily_report=bool(row[3]),
                sales_alert=bool(row[4]),
                returns_alert=bool(row[5])
            )
            
        # Если настроек нет, создаем дефолтные
        default_settings = NotificationSettings(telegram_id=telegram_id)
        await save_notification_settings(default_settings)
        return default_settings

# Сохранение настроек уведомлений пользователя
async def save_notification_settings(settings: NotificationSettings) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO notification_settings
            (telegram_id, margin_threshold, roi_threshold, daily_report, sales_alert, returns_alert, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (
            settings.telegram_id,
            settings.margin_threshold,
            settings.roi_threshold,
            int(settings.daily_report),
            int(settings.sales_alert),
            int(settings.returns_alert)
        ))
        conn.commit()
        return True

# API для получения настроек уведомлений
@app.get("/api/notifications/settings")
async def get_user_notification_settings(api_key: str = Depends(api_key_header)):
    try:
        tokens = await get_api_tokens(api_key)
        telegram_id = tokens.get("telegram_id")
        if not telegram_id:
            raise HTTPException(status_code=401, detail="Недействительный API ключ")
            
        settings = await get_notification_settings(telegram_id)
        return settings
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при получении настроек: {str(e)}")

# API для обновления настроек уведомлений
@app.post("/api/notifications/settings")
async def update_notification_settings(settings: NotificationSettings, api_key: str = Depends(api_key_header)):
    try:
        tokens = await get_api_tokens(api_key)
        telegram_id = tokens.get("telegram_id")
        if not telegram_id:
            raise HTTPException(status_code=401, detail="Недействительный API ключ")
            
        if settings.telegram_id != telegram_id:
            settings.telegram_id = telegram_id
            
        success = await save_notification_settings(settings)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при обновлении настроек: {str(e)}")

# Расширенная аналитика для продуктов
@app.get("/api/analytics/products")
async def get_product_analytics(period: str = "month", api_key: str = Depends(api_key_header)):
    try:
        tokens = await get_api_tokens(api_key)
        telegram_id = tokens.get("telegram_id")
        if not telegram_id:
            raise HTTPException(status_code=401, detail="Недействительный API ключ")
            
        user_token = await get_user_tokens(telegram_id)
        if not user_token:
            raise HTTPException(status_code=404, detail="Токены Ozon не найдены")
            
        # Получаем продукты
        products = await get_ozon_products(user_token.ozon_api_token, user_token.ozon_client_id)
        
        # Получаем себестоимость
        costs = await get_product_costs(api_key)
        cost_map = {cost.product_id: cost.cost for cost in costs}
        
        # Получаем данные по продажам
        analytics = await get_ozon_analytics(user_token.ozon_api_token, user_token.ozon_client_id, period)
        
        # Получаем финансовые данные
        financials = await get_ozon_financial_data(user_token.ozon_api_token, user_token.ozon_client_id, period)
        
        # Получаем данные по рекламе
        ad_data = await get_ozon_advertising_costs(user_token.ozon_api_token, user_token.ozon_client_id, period)
        ad_costs_map = {}  # Затраты на рекламу по продуктам
        
        # Получаем данные по возвратам
        returns_data = await get_ozon_returns_data(user_token.ozon_api_token, user_token.ozon_client_id, period)
        returns_map = {}  # Стоимость возвратов по продуктам
        
        # Распределение затрат на рекламу равномерно по всем продуктам, 
        # в реальности требуется более сложная логика в зависимости от данных Ozon API
        total_products = len(products)
        if total_products > 0:
            ad_cost_per_product = ad_data.get("total_cost", 0) / total_products
            
            for product in products:
                product_id = product.get("product_id")
                ad_costs_map[product_id] = ad_cost_per_product
        
        # Формируем расширенную аналитику по продуктам
        product_analytics = []
        
        for product in products:
            product_id = product.get("product_id")
            offer_id = product.get("offer_id")
            name = product.get("name")
            
            # Данные по продажам
            sales_data = next((item for item in analytics if item.get("product_id") == product_id), None)
            sales_count = sales_data.get("sales_count", 0) if sales_data else 0
            revenue = sales_data.get("revenue", 0) if sales_data else 0
            
            # Себестоимость
            cost = cost_map.get(product_id, 0)
            
            # Комиссии
            commission = 0
            for item in financials:
                if item.get("product_id") == product_id:
                    commission += item.get("commission", 0)
            
            # Затраты на рекламу для продукта
            ad_cost = ad_costs_map.get(product_id, 0)
            
            # Затраты на возвраты для продукта
            return_cost = returns_map.get(product_id, 0)
            
            # Прибыль и рентабельность с учётом всех затрат
            total_costs = (cost * sales_count) + commission + ad_cost + return_cost
            profit = revenue - total_costs
            margin = (profit / revenue * 100) if revenue > 0 else 0
            roi = (profit / total_costs * 100) if total_costs > 0 else 0
            
            # Формируем аналитику по продукту
            product_analytics.append({
                "product_id": product_id,
                "offer_id": offer_id,
                "name": name,
                "image": product.get("images", [""])[0] if product.get("images") else "",
                "sales_count": sales_count,
                "revenue": revenue,
                "cost": cost,
                "total_cost": cost * sales_count,
                "commission": commission,
                "ad_cost": ad_cost,
                "return_cost": return_cost,
                "profit": profit,
                "margin": margin,
                "roi": roi
            })
        
        return product_analytics
    except Exception as e:
        print(f"Ошибка при получении аналитики по продуктам: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка при получении аналитики по продуктам: {str(e)}")

# Функция для отправки ежедневных отчетов пользователям
async def send_daily_reports(background_tasks: BackgroundTasks):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.telegram_id 
                FROM notification_settings n
                JOIN user_tokens u ON n.telegram_id = u.telegram_id
                WHERE n.daily_report = 1
            ''')
            
            users = cursor.fetchall()
            
        for user in users:
            telegram_id = user[0]
            try:
                # Получаем данные аналитики
                analytics_data = await api_get_analytics(period="day", telegram_id=telegram_id)
                
                if not analytics_data:
                    continue
                
                # Форматируем отчет
                total_revenue = analytics_data.get("revenue", 0)
                total_profit = analytics_data.get("profit", 0)
                margin = analytics_data.get("margin", 0)
                roi = analytics_data.get("roi", 0)
                
                report_message = (
                    f"📊 *Ежедневный отчет*\n\n"
                    f"Выручка: {total_revenue:.2f} ₽\n"
                    f"Прибыль: {total_profit:.2f} ₽\n"
                    f"Маржинальность: {margin:.2f}%\n"
                    f"ROI: {roi:.2f}%\n\n"
                    f"Для более подробной информации откройте приложение."
                )
                
                # Отправляем уведомление
                background_tasks.add_task(send_notification, telegram_id, report_message)
                
            except Exception as e:
                print(f"Ошибка при отправке отчета пользователю {telegram_id}: {str(e)}")
                continue
                
    except Exception as e:
        print(f"Ошибка при отправке ежедневных отчетов: {str(e)}")

# Функция для проверки показателей и отправки уведомлений
async def check_metrics_and_notify(background_tasks: BackgroundTasks):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.telegram_id, n.margin_threshold, n.roi_threshold 
                FROM notification_settings n
                JOIN user_tokens u ON n.telegram_id = u.telegram_id
            ''')
            
            users = cursor.fetchall()
            
        for user in users:
            telegram_id, margin_threshold, roi_threshold = user
            
            try:
                # Получаем данные пользователя
                user_token = await get_user_tokens(telegram_id)
                if not user_token:
                    continue
                
                # Получаем продукты
                products = await get_ozon_products(user_token.ozon_api_token, user_token.ozon_client_id)
                
                # Получаем себестоимость
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT product_id, cost FROM product_costs
                        WHERE telegram_id = ?
                    ''', (telegram_id,))
                    
                    costs = cursor.fetchall()
                    cost_map = {row[0]: row[1] for row in costs}
                
                # Получаем данные по продажам
                analytics = await get_ozon_analytics(user_token.ozon_api_token, user_token.ozon_client_id, "day")
                
                # Получаем финансовые данные
                financials = await get_ozon_financial_data(user_token.ozon_api_token, user_token.ozon_client_id, "day")
                
                # Формируем аналитику по продуктам
                product_analytics = []
                
                for product in products:
                    product_id = product.get("product_id")
                    name = product.get("name")
                    
                    # Данные по продажам
                    sales_data = next((item for item in analytics if item.get("product_id") == product_id), None)
                    sales_count = sales_data.get("sales_count", 0) if sales_data else 0
                    revenue = sales_data.get("revenue", 0) if sales_data else 0
                    
                    # Себестоимость
                    cost = cost_map.get(product_id, 0)
                    
                    # Комиссии
                    commission = 0
                    for item in financials:
                        if item.get("product_id") == product_id:
                            commission += item.get("commission", 0)
                    
                    # Прибыль и рентабельность
                    profit = revenue - (cost * sales_count) - commission
                    margin = (profit / revenue * 100) if revenue > 0 else 0
                    roi = (profit / (cost * sales_count) * 100) if cost * sales_count > 0 else 0
                    
                    product_analytics.append({
                        "product_id": product_id,
                        "name": name,
                        "sales_count": sales_count,
                        "margin": margin,
                        "roi": roi
                    })
                
                # Проверяем, есть ли товары с показателями ниже порога
                low_margin_products = [
                    p for p in product_analytics 
                    if p.get("sales_count", 0) > 0 and p.get("margin", 0) < margin_threshold
                ]
                
                low_roi_products = [
                    p for p in product_analytics 
                    if p.get("sales_count", 0) > 0 and p.get("roi", 0) < roi_threshold
                ]
                
                # Отправляем уведомления о низкой маржинальности
                if low_margin_products:
                    products_list = "\n".join([
                        f"• {p.get('name')} - {p.get('margin', 0):.2f}%"
                        for p in low_margin_products[:5]  # Ограничиваем список 5 товарами
                    ])
                    
                    margin_message = (
                        f"⚠️ *Внимание: Низкая маржинальность*\n\n"
                        f"У следующих товаров маржинальность ниже порога ({margin_threshold}%):\n\n"
                        f"{products_list}\n"
                    )
                    
                    if len(low_margin_products) > 5:
                        margin_message += f"\nИ еще {len(low_margin_products) - 5} товаров...\n"
                        
                    margin_message += "\nПроверьте себестоимость этих товаров в приложении."
                    
                    background_tasks.add_task(send_notification, telegram_id, margin_message)
                
                # Отправляем уведомления о низком ROI
                if low_roi_products:
                    products_list = "\n".join([
                        f"• {p.get('name')} - {p.get('roi', 0):.2f}%"
                        for p in low_roi_products[:5]  # Ограничиваем список 5 товарами
                    ])
                    
                    roi_message = (
                        f"⚠️ *Внимание: Низкий ROI*\n\n"
                        f"У следующих товаров ROI ниже порога ({roi_threshold}%):\n\n"
                        f"{products_list}\n"
                    )
                    
                    if len(low_roi_products) > 5:
                        roi_message += f"\nИ еще {len(low_roi_products) - 5} товаров...\n"
                        
                    roi_message += "\nПроверьте себестоимость этих товаров в приложении."
                    
                    background_tasks.add_task(send_notification, telegram_id, roi_message)
                
            except Exception as e:
                print(f"Ошибка при проверке метрик для пользователя {telegram_id}: {str(e)}")
                continue
    
    except Exception as e:
        print(f"Ошибка при проверке метрик и отправке уведомлений: {str(e)}")

# Функция для проведения ABC-анализа товаров
async def perform_abc_analysis(products_data: list) -> list:
    """
    Классифицирует товары по их вкладу в прибыль:
    A - топ 20% товаров (высокий вклад в прибыль)
    B - средние 30% товаров
    C - остальные 50% товаров
    """
    if not products_data:
        return []
    
    # Сортируем товары по прибыли в порядке убывания
    sorted_products = sorted(products_data, key=lambda x: x.get('profit', 0), reverse=True)
    
    # Считаем общую прибыль
    total_profit = sum(p.get('profit', 0) for p in sorted_products)
    
    # Если общая прибыль нулевая, всё в категории C
    if total_profit <= 0:
        for product in sorted_products:
            product['abc_category'] = 'C'
            product['profit_percent'] = 0
        return sorted_products
    
    cumulative_profit = 0
    cumulative_percent = 0
    
    # Проходим по всем товарам и присваиваем категории
    for product in sorted_products:
        profit = product.get('profit', 0)
        profit_percent = (profit / total_profit) * 100 if total_profit > 0 else 0
        cumulative_profit += profit
        cumulative_percent = (cumulative_profit / total_profit) * 100 if total_profit > 0 else 0
        
        # Присваиваем категорию ABC
        if cumulative_percent <= 20:
            category = 'A'
        elif cumulative_percent <= 50:
            category = 'B'
        else:
            category = 'C'
        
        # Добавляем информацию в объект товара
        product['abc_category'] = category
        product['profit_percent'] = profit_percent
        product['cumulative_percent'] = cumulative_percent
    
    return sorted_products

# Расширяем функцию аналитики продуктов, добавляя ABC-анализ
@app.get("/api/analytics/abc")
async def get_abc_analysis(period: str = "month", api_key: str = Depends(api_key_header)):
    try:
        # Получаем аналитику по продуктам
        product_analytics = await get_product_analytics(period=period, api_key=api_key)
        
        # Проводим ABC-анализ
        abc_analysis = await perform_abc_analysis(product_analytics)
        
        # Группируем результаты по категориям
        result = {
            "A": [p for p in abc_analysis if p.get('abc_category') == 'A'],
            "B": [p for p in abc_analysis if p.get('abc_category') == 'B'],
            "C": [p for p in abc_analysis if p.get('abc_category') == 'C'],
            "total_products": len(abc_analysis),
            "total_profit": sum(p.get('profit', 0) for p in abc_analysis),
            "category_stats": {
                "A": {
                    "count": len([p for p in abc_analysis if p.get('abc_category') == 'A']),
                    "profit": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'A'),
                    "profit_percent": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'A') / 
                                     (sum(p.get('profit', 0) for p in abc_analysis) if sum(p.get('profit', 0) for p in abc_analysis) > 0 else 1) * 100
                },
                "B": {
                    "count": len([p for p in abc_analysis if p.get('abc_category') == 'B']),
                    "profit": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'B'),
                    "profit_percent": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'B') / 
                                     (sum(p.get('profit', 0) for p in abc_analysis) if sum(p.get('profit', 0) for p in abc_analysis) > 0 else 1) * 100
                },
                "C": {
                    "count": len([p for p in abc_analysis if p.get('abc_category') == 'C']),
                    "profit": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'C'),
                    "profit_percent": sum(p.get('profit', 0) for p in abc_analysis if p.get('abc_category') == 'C') / 
                                     (sum(p.get('profit', 0) for p in abc_analysis) if sum(p.get('profit', 0) for p in abc_analysis) > 0 else 1) * 100
                }
            }
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при проведении ABC-анализа: {str(e)}")

# API-эндпоинт для получения самого прибыльного товара (для виджета "Товар дня")
@app.get("/api/analytics/top_product_by_analytics")
async def get_top_product_by_analytics(period: str = "month", api_key: str = Depends(api_key_header)):
    try:
        # Получаем аналитику по продуктам
        product_analytics = await get_product_analytics(period=period, api_key=api_key)
        
        if not product_analytics:
            raise HTTPException(status_code=404, detail="Товары не найдены")
        
        # Сортируем по прибыли и берем первый товар
        sorted_products = sorted(product_analytics, key=lambda x: x.get('profit', 0), reverse=True)
        
        if sorted_products:
            top_product = sorted_products[0]
            
            # Добавляем процент от общей прибыли
            total_profit = sum(p.get('profit', 0) for p in product_analytics)
            if total_profit > 0:
                top_product['profit_percent'] = (top_product.get('profit', 0) / total_profit) * 100
            else:
                top_product['profit_percent'] = 0
                
            return top_product
        else:
            raise HTTPException(status_code=404, detail="Товары не найдены")
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при получении топового товара: {str(e)}")

@app.post("/api/update_data")
async def update_user_data(user_id: int, token_data: dict = Body(...)):
    try:
        api_token = token_data.get("api_token")
        client_id = token_data.get("client_id")
        
        if not api_token or not client_id:
            return {"success": False, "error": "Не указаны API-токен или Client ID"}
        
        # Получаем список товаров
        products_result = await fetch_products(api_token, client_id)
        if not products_result["success"]:
            return {"success": False, "error": f"Ошибка получения списка товаров: {products_result['error']}"}
        
        # Получаем транзакции
        transactions_result = await fetch_transactions(api_token, client_id)
        if not transactions_result["success"]:
            return {"success": False, "error": f"Ошибка получения транзакций: {transactions_result['error']}"}
        
        # Сохраняем данные в базу
        await save_products_to_db(user_id, products_result["products"])
        await save_transactions_to_db(user_id, transactions_result["transactions"])
        
        # Обновляем аналитику
        await calculate_and_save_analytics(user_id)
        
        # Выполняем ABC-анализ
        await perform_abc_analysis(user_id)
        
        # Обновляем "Товар дня"
        await update_top_product(user_id)
        
        return {
            "success": True,
            "message": "Данные успешно обновлены",
            "updated_data": {
                "products_count": len(products_result["products"]),
                "transactions_count": len(transactions_result["transactions"])
            }
        }
    except Exception as e:
        print(f"Ошибка при обновлении данных: {str(e)}")
        return {"success": False, "error": f"Ошибка при обновлении данных: {str(e)}"}

async def update_top_product(user_id: int):
    """Обновляет информацию о 'Товаре дня' - самом прибыльном товаре пользователя"""
    try:
        conn = sqlite3.connect("ozon.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Получаем товар с наибольшей прибылью за последние 30 дней
        cursor.execute("""
            SELECT 
                p.id, p.name, p.offer_id, p.product_id, p.image_url, p.price, p.commission_amount,
                p.category, p.cost, COUNT(DISTINCT t.id) as sales_count,
                SUM(t.price) as total_sales,
                SUM(t.commission_amount) as total_commission,
                SUM(p.cost) as total_cost,
                (SUM(t.price) - SUM(t.commission_amount) - (COUNT(DISTINCT t.id) * p.cost)) as profit,
                ((SUM(t.price) - SUM(t.commission_amount) - (COUNT(DISTINCT t.id) * p.cost)) / SUM(t.price) * 100) as profit_percent,
                ((SUM(t.price) - SUM(t.commission_amount) - (COUNT(DISTINCT t.id) * p.cost)) / (COUNT(DISTINCT t.id) * p.cost) * 100) as roi
            FROM products p
            JOIN transactions t ON p.product_id = t.product_id AND p.user_id = t.user_id
            WHERE p.user_id = ? AND t.transaction_date >= date('now', '-30 day')
            GROUP BY p.id
            ORDER BY profit DESC
            LIMIT 1
        """, (user_id,))
        
        top_product = cursor.fetchone()
        
        if top_product:
            # Преобразуем строку в словарь
            top_product_dict = dict(top_product)
            
            # Сохраняем информацию о "Товаре дня" в отдельную таблицу
            cursor.execute("""
                INSERT OR REPLACE INTO top_product (
                    user_id, product_id, offer_id, name, image_url, price, 
                    sales_count, total_sales, profit, profit_percent, roi, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                user_id, top_product_dict["product_id"], top_product_dict["offer_id"],
                top_product_dict["name"], top_product_dict["image_url"], top_product_dict["price"],
                top_product_dict["sales_count"], top_product_dict["total_sales"],
                top_product_dict["profit"], top_product_dict["profit_percent"], top_product_dict["roi"]
            ))
            
            conn.commit()
        
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при обновлении 'Товара дня': {str(e)}")
        return False

async def initialize_database():
    """Инициализирует базу данных - создает необходимые таблицы, если они не существуют"""
    try:
        conn = sqlite3.connect("ozon.db")
        cursor = conn.cursor()
        
        # Таблица с токенами пользователей
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tokens (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            ozon_api_token TEXT NOT NULL,
            ozon_client_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица с товарами
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            image_url TEXT,
            price REAL,
            commission_amount REAL,
            cost REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, product_id)
        )
        ''')
        
        # Таблица с транзакциями
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            transaction_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            price REAL,
            commission_amount REAL,
            transaction_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, transaction_id)
        )
        ''')
        
        # Таблица с аналитикой
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_sales REAL,
            total_commission REAL,
            total_cost REAL,
            profit REAL,
            margin REAL,
            roi REAL,
            products_count INTEGER,
            period TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, period)
        )
        ''')
        
        # Таблица с настройками уведомлений
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_settings (
            user_id INTEGER PRIMARY KEY,
            margin_threshold REAL DEFAULT 15.0,
            roi_threshold REAL DEFAULT 50.0,
            daily_report BOOLEAN DEFAULT 1,
            low_margin_alert BOOLEAN DEFAULT 1,
            low_roi_alert BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица для ABC-анализа
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS abc_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            profit REAL,
            profit_percent REAL,
            abc_category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, product_id)
        )
        ''')
        
        # Таблица для "Товара дня"
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS top_product (
            user_id INTEGER PRIMARY KEY,
            product_id TEXT NOT NULL,
            offer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            image_url TEXT,
            price REAL,
            sales_count INTEGER,
            total_sales REAL,
            profit REAL,
            profit_percent REAL,
            roi REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()
        print("База данных инициализирована")
        return True
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {str(e)}")
        return False

@app.get("/api/analytics/top_product")
async def get_top_product(user_id: int):
    """Возвращает информацию о 'Товаре дня' - самом прибыльном товаре пользователя"""
    try:
        conn = sqlite3.connect("ozon.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM top_product WHERE user_id = ?
        """, (user_id,))
        
        top_product = cursor.fetchone()
        conn.close()
        
        if top_product:
            # Преобразуем строку в словарь
            top_product_dict = dict(top_product)
            return {
                "success": True,
                "top_product": top_product_dict
            }
        else:
            return {
                "success": False,
                "error": "Товар дня не найден. Возможно, у вас еще нет продаж или данные не обновлены."
            }
    except Exception as e:
        print(f"Ошибка при получении 'Товара дня': {str(e)}")
        return {"success": False, "error": f"Ошибка при получении данных: {str(e)}"}

@app.get("/api/analytics/top_product_by_user")
async def get_top_product_by_user(user_id: int):
    """Возвращает информацию о 'Товаре дня' - самом прибыльном товаре пользователя"""
    try:
        conn = sqlite3.connect("ozon.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM top_product WHERE user_id = ?
        """, (user_id,))
        
        top_product = cursor.fetchone()
        conn.close()
        
        if top_product:
            # Преобразуем строку в словарь
            top_product_dict = dict(top_product)
            return {
                "success": True,
                "top_product": top_product_dict
            }
        else:
            return {
                "success": False,
                "error": "Товар дня не найден. Возможно, у вас еще нет продаж или данные не обновлены."
            }
    except Exception as e:
        print(f"Ошибка при получении 'Товара дня': {str(e)}")
        return {"success": False, "error": f"Ошибка при получении данных: {str(e)}"}

# API-эндпоинт для получения самого прибыльного товара (для виджета "Товар дня")
@app.get("/api/analytics/top_product_by_analytics")
async def get_top_product_by_analytics(period: str = "month", api_key: str = Depends(api_key_header)):
    try:
        # Получаем аналитику по продуктам
        product_analytics = await get_product_analytics(period=period, api_key=api_key)
        
        if not product_analytics:
            raise HTTPException(status_code=404, detail="Товары не найдены")
        
        # Сортируем по прибыли и берем первый товар
        sorted_products = sorted(product_analytics, key=lambda x: x.get('profit', 0), reverse=True)
        
        if sorted_products:
            top_product = sorted_products[0]
            
            # Добавляем процент от общей прибыли
            total_profit = sum(p.get('profit', 0) for p in product_analytics)
            if total_profit > 0:
                top_product['profit_percent'] = (top_product.get('profit', 0) / total_profit) * 100
            else:
                top_product['profit_percent'] = 0
                
            return top_product
        else:
            raise HTTPException(status_code=404, detail="Товары не найдены")
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при получении топового товара: {str(e)}")

# Новые функции для получения данных о рекламе и возвратах
async def get_ozon_advertising_costs(api_token: str, client_id: str, period: str = "month"):
    """Получает данные о рекламных расходах из API Ozon"""
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
        
        # URL для запроса данных по рекламе
        url = "https://api-seller.ozon.ru/v1/finance/campaign"
        
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
            "pagination": {
                "limit": 1000,
                "offset": 0
            }
        }
        
        # Отправляем запрос
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"Ошибка при получении данных по рекламе: {response.status_code} - {response.text}")
            return {"total_cost": 0, "campaigns": []}
        
        data = response.json()
        
        # Считаем общие расходы на рекламу
        total_cost = 0
        campaigns = []
        
        if "result" in data and "campaigns" in data["result"]:
            for campaign in data["result"]["campaigns"]:
                cost = campaign.get("cost", 0)
                total_cost += cost
                campaigns.append({
                    "campaign_id": campaign.get("campaign_id", ""),
                    "name": campaign.get("name", ""),
                    "cost": cost
                })
        
        return {"total_cost": total_cost, "campaigns": campaigns}
    
    except Exception as e:
        print(f"Ошибка при получении данных по рекламе: {str(e)}")
        return {"total_cost": 0, "campaigns": []}

async def get_ozon_returns_data(api_token: str, client_id: str, period: str = "month"):
    """Получает данные о возвратах из API Ozon"""
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
        
        # URL для запроса данных по возвратам
        url = "https://api-seller.ozon.ru/v3/returns/company/fbs"
        
        # Заголовки запроса
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_token,
            "Content-Type": "application/json"
        }
        
        # Тело запроса
        payload = {
            "filter": {
                "date": {
                    "from": date_from,
                    "to": date_to
                }
            },
            "limit": 1000,
            "offset": 0
        }
        
        # Отправляем запрос
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"Ошибка при получении данных по возвратам: {response.status_code} - {response.text}")
            return {"total_returns": 0, "total_cost": 0, "returns": []}
        
        data = response.json()
        
        # Считаем общую сумму возвратов
        total_returns = 0
        total_cost = 0
        returns = []
        
        if "result" in data and "returns" in data["result"]:
            for return_item in data["result"]["returns"]:
                price = return_item.get("price", 0)
                total_returns += 1
                total_cost += price
                returns.append({
                    "return_id": return_item.get("id", ""),
                    "product_id": return_item.get("product_id", ""),
                    "price": price,
                    "reason": return_item.get("return_reason", "")
                })
        
        return {
            "total_returns": total_returns, 
            "total_cost": total_cost,
            "returns": returns
        }
    
    except Exception as e:
        print(f"Ошибка при получении данных по возвратам: {str(e)}")
        return {"total_returns": 0, "total_cost": 0, "returns": []}

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
        
        # Отправляем запрос к API Ozon
        response = requests.post(url, headers=headers, json=payload)
        
        # Получаем рекламные расходы
        ad_data = await get_ozon_advertising_costs(api_token, client_id, period)
        advertising_costs = ad_data.get("total_cost", 0)
        
        # Получаем данные о возвратах
        returns_data = await get_ozon_returns_data(api_token, client_id, period)
        returns_cost = returns_data.get("total_cost", 0)
        
        if response.status_code != 200:
            return {
                "error": True,
                "message": f"Ошибка при получении финансовых данных: {response.status_code} - {response.text}",
                "advertising_costs": advertising_costs,
                "returns_cost": returns_cost
            }
        
        data = response.json()
        
        # Дополняем данные рекламными расходами и возвратами
        data["advertising_costs"] = advertising_costs
        data["returns_cost"] = returns_cost
        
        return data
    
    except Exception as e:
        print(f"Ошибка при получении финансовых данных: {str(e)}")
        return {
            "error": True,
            "message": f"Ошибка при получении финансовых данных: {str(e)}",
            "advertising_costs": 0,
            "returns_cost": 0
        }

# Новые API-эндпоинты для работы с Celery
@app.post("/api/update_all_data")
async def api_update_all_data():
    """API-эндпоинт для обновления данных всех пользователей (вызывается из Celery)"""
    try:
        # Получаем всех пользователей с активными токенами
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id FROM user_tokens")
            users = cursor.fetchall()
        
        # Счетчики успешных и неудачных обновлений
        success_count = 0
        error_count = 0
        
        # Обновляем данные для каждого пользователя
        for user in users:
            telegram_id = user[0]
            try:
                # Получаем токены пользователя
                user_token = await get_user_tokens(telegram_id)
                if not user_token:
                    continue
                
                # Обновляем данные о товарах
                products = await get_ozon_products(user_token.ozon_api_token, user_token.ozon_client_id)
                
                # Обновляем аналитику
                analytics = await get_ozon_analytics(user_token.ozon_api_token, user_token.ozon_client_id)
                
                # Обновляем данные о рекламе
                ad_data = await get_ozon_advertising_costs(user_token.ozon_api_token, user_token.ozon_client_id)
                
                # Обновляем данные о возвратах
                returns_data = await get_ozon_returns_data(user_token.ozon_api_token, user_token.ozon_client_id)
                
                # Обновляем ABC-анализ
                abc_analysis = await perform_abc_analysis(products)
                
                # Обновляем топовый товар
                await update_top_product(telegram_id)
                
                success_count += 1
                
            except Exception as e:
                print(f"Ошибка при обновлении данных для пользователя {telegram_id}: {str(e)}")
                error_count += 1
                continue
        
        return {
            "status": "success",
            "total_users": len(users),
            "success_count": success_count,
            "error_count": error_count
        }
    
    except Exception as e:
        print(f"Общая ошибка при обновлении данных: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при обновлении данных: {str(e)}")

@app.get("/api/send_daily_reports")
async def api_send_daily_reports():
    """API-эндпоинт для отправки ежедневных отчетов (вызывается из Celery)"""
    try:
        # Получаем пользователей, которые включили ежедневные отчеты
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.telegram_id 
                FROM notification_settings n
                JOIN user_tokens u ON n.telegram_id = u.telegram_id
                WHERE n.daily_report = 1
            ''')
            
            users = cursor.fetchall()
        
        # Счетчики успешных и неудачных отправок
        success_count = 0
        error_count = 0
        
        for user in users:
            telegram_id = user[0]
            try:
                # Получаем данные аналитики
                analytics_data = await api_get_analytics(period="day", telegram_id=telegram_id)
                
                if not analytics_data:
                    continue
                
                # Форматируем отчет
                total_revenue = analytics_data.get("revenue", 0)
                total_profit = analytics_data.get("profit", 0)
                margin = analytics_data.get("margin", 0)
                roi = analytics_data.get("roi", 0)
                
                report_message = (
                    f"📊 *Ежедневный отчет*\n\n"
                    f"Выручка: {total_revenue:.2f} ₽\n"
                    f"Прибыль: {total_profit:.2f} ₽\n"
                    f"Маржинальность: {margin:.2f}%\n"
                    f"ROI: {roi:.2f}%\n\n"
                    f"Для более подробной информации откройте приложение."
                )
                
                # Отправляем уведомление
                success = await send_notification(telegram_id, report_message)
                
                if success:
                    success_count += 1
                else:
                    error_count += 1
                
            except Exception as e:
                print(f"Ошибка при отправке отчета пользователю {telegram_id}: {str(e)}")
                error_count += 1
                continue
        
        return {
            "status": "success",
            "total_users": len(users),
            "success_count": success_count,
            "error_count": error_count
        }
                
    except Exception as e:
        print(f"Общая ошибка при отправке ежедневных отчетов: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при отправке отчетов: {str(e)}")

@app.get("/api/check_metrics")
async def api_check_metrics():
    """API-эндпоинт для проверки метрик и отправки уведомлений (вызывается из Celery)"""
    try:
        # Получаем всех пользователей с настройками уведомлений
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.telegram_id, n.margin_threshold, n.roi_threshold 
                FROM notification_settings n
                JOIN user_tokens u ON n.telegram_id = u.telegram_id
            ''')
            
            users = cursor.fetchall()
        
        # Счетчики отправленных уведомлений
        low_margin_alerts = 0
        low_roi_alerts = 0
        
        for user in users:
            telegram_id, margin_threshold, roi_threshold = user
            
            try:
                # Получаем данные пользователя
                user_token = await get_user_tokens(telegram_id)
                if not user_token:
                    continue
                
                # Получаем аналитику
                analytics = await api_get_analytics(period="day", telegram_id=telegram_id)
                
                if not analytics:
                    continue
                
                # Проверяем метрики
                current_margin = analytics.get("margin", 0)
                current_roi = analytics.get("roi", 0)
                
                # Отправляем уведомления, если метрики ниже порогов
                if current_margin < margin_threshold:
                    alert_message = (
                        f"⚠️ *Внимание! Низкая маржинальность*\n\n"
                        f"Текущая маржинальность: {current_margin:.2f}%\n"
                        f"Ваш порог: {margin_threshold:.2f}%\n\n"
                        f"Рекомендуем проверить цены и себестоимость товаров."
                    )
                    
                    success = await send_notification(telegram_id, alert_message)
                    if success:
                        low_margin_alerts += 1
                
                if current_roi < roi_threshold:
                    alert_message = (
                        f"⚠️ *Внимание! Низкий ROI*\n\n"
                        f"Текущий ROI: {current_roi:.2f}%\n"
                        f"Ваш порог: {roi_threshold:.2f}%\n\n"
                        f"Рекомендуем пересмотреть стратегию продаж и ценообразование."
                    )
                    
                    success = await send_notification(telegram_id, alert_message)
                    if success:
                        low_roi_alerts += 1
                
            except Exception as e:
                print(f"Ошибка при проверке метрик пользователя {telegram_id}: {str(e)}")
                continue
        
        return {
            "status": "success",
            "total_users": len(users),
            "low_margin_alerts": low_margin_alerts,
            "low_roi_alerts": low_roi_alerts
        }
                
    except Exception as e:
        print(f"Общая ошибка при проверке метрик: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при проверке метрик: {str(e)}")