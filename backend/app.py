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
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import sys
import importlib.util
from telegram.ext import ApplicationBuilder, ContextTypes

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
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
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
    bot = telegram.Bot(token=BOT_TOKEN)
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
            f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
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

async def handle_command(command, update_data):
    """Обрабатывает команды от Telegram"""
    try:
        chat_id = update_data.get("chat", {}).get("id")
        user_id = update_data.get("from", {}).get("id")
        username = update_data.get("from", {}).get("username", "пользователь")
        first_name = update_data.get("from", {}).get("first_name", username)
        
        # Создаем клавиатуру с кнопками
        keyboard = get_main_keyboard()
        # Создаем инлайн клавиатуру с кнопкой приложения
        app_button = get_app_button()
        
        # Обрабатываем команды
        if command == "start":
            # Сбрасываем состояние пользователя при начале работы с ботом
            if user_id in user_states:
                del user_states[user_id]
            
            welcome_message = (
                f"👋 Привет, {first_name}!\n\n"
                "Я бот для работы с API Ozon. Я помогу вам получать и анализировать данные вашего магазина на Ozon.\n\n"
                "🔑 Для начала работы установите токены Ozon API с помощью команды /set_token\n"
                "❓ Используйте /help для получения справки о доступных командах"
            )
            
            await bot.send_message(
                chat_id=chat_id,
                text=welcome_message,
                reply_markup=keyboard
            )
        
        elif command == "help":
            # Сбрасываем состояние пользователя
            if user_id in user_states:
                del user_states[user_id]
                
            help_message = (
                "📚 *Доступные команды:*\n\n"
                "🚀 */start* - Начать работу с ботом\n"
                "🔑 */set_token* - Установить API токен и Client ID Ozon\n"
                "ℹ️ */status* - Проверить статус токенов\n"
                "📊 */stats* - Получить базовую статистику по магазину\n"
                "🔄 */verify* - Проверить валидность токенов\n"
                "❌ */delete_tokens* - Удалить сохраненные токены\n"
                "❓ */help* - Показать эту справку"
            )
            
            await bot.send_message(
                chat_id=chat_id,
                text=help_message,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        
        elif command == "set_token":
            # Инициируем процесс установки токена
            user_states[user_id] = {
                "state": "waiting_for_api_token"
            }
            
            instructions_message = (
                "🔑 *Установка токенов API Ozon*\n\n"
                "*Шаг 1:* Отправьте мне ваш API токен.\n\n"
                "Как получить API токен и Client ID:\n"
                "1️⃣ Войдите в [личный кабинет Ozon](https://seller.ozon.ru/)\n"
                "2️⃣ Перейдите в раздел *API ключи* (в меню слева)\n"
                "3️⃣ Создайте новый ключ, если у вас его еще нет\n"
                "4️⃣ Скопируйте API-ключ и отправьте мне\n\n"
                "Пример API-ключа: `a1b2c3de-f4g5-h6i7-j8k9-lmnopqrst012`\n\n"
                "Просто скопируйте ваш API токен из личного кабинета Ozon и отправьте его в сообщении."
            )
            
            # Отправляем инструкцию пользователю
            await bot.send_message(
                chat_id=chat_id,
                text=instructions_message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=keyboard
            )
            
            # Добавляем поясняющее изображение, если оно есть
            # await bot.send_photo(
            #     chat_id=chat_id,
            #     photo=open("path/to/api_token_screenshot.jpg", "rb"),
            #     caption="Пример, где найти API токен в личном кабинете Ozon"
            # )
        
        elif command == "status":
            # Сбрасываем состояние пользователя
            if user_id in user_states:
                del user_states[user_id]
            
            # Получаем информацию о токенах пользователя
            user_token = get_user_token(user_id)
            
            if user_token:
                status_message = (
                    "✅ *Токены API установлены*\n\n"
                    f"👤 Пользователь: `{username}` (ID: `{user_id}`)\n"
                    f"🔑 Client ID: `{user_token.ozon_client_id}`\n"
                    f"🔐 API Token: `{user_token.ozon_api_token[:5]}...{user_token.ozon_api_token[-5:]}`\n\n"
                    "Вы можете использовать веб-интерфейс для анализа данных вашего магазина."
                )
                
                await bot.send_message(
                    chat_id=chat_id,
                    text=status_message,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                
                # Добавляем кнопку для открытия приложения
                await bot.send_message(
                    chat_id=chat_id,
                    text="Открыть веб-интерфейс:",
                    reply_markup=app_button
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="❌ API токены не установлены.\n\nИспользуйте команду /set_token для установки токенов Ozon API.",
                    reply_markup=keyboard
                )
        
        elif command == "delete_tokens":
            # Сбрасываем состояние пользователя
            if user_id in user_states:
                del user_states[user_id]
                
            # Проверяем наличие токенов у пользователя
            user_token = get_user_token(user_id)
            
            if user_token:
                # Удаляем токены из базы данных
                delete_user_token(user_id)
                
                await bot.send_message(
                    chat_id=chat_id,
                    text="✅ Токены API успешно удалены.",
                    reply_markup=keyboard
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="ℹ️ У вас не было сохраненных токенов API.",
                    reply_markup=keyboard
                )
        
        elif command == "stats":
            # Сбрасываем состояние пользователя
            if user_id in user_states:
                del user_states[user_id]
                
            user_token = get_user_token(user_id)
            
            if not user_token:
                await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Невозможно получить статистику. API токены не установлены.\n\n"
                         "Пожалуйста, используйте команду /set_token для установки токенов Ozon API.",
                    reply_markup=keyboard
                )
                return
            
            await bot.send_message(
                chat_id=chat_id,
                text="🔄 Получаю статистику из Ozon API...",
                reply_markup=keyboard
            )
            
            # Получаем статистику из API Ozon
            try:
                analytics_data, analytics_message = await get_ozon_analytics(user_token.ozon_api_token, user_token.ozon_client_id)
                financial_data, financial_message = await get_ozon_financial_data(user_token.ozon_api_token, user_token.ozon_client_id)
                
                if not analytics_data and not financial_data:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Ошибка при получении данных из API Ozon:\n\n{analytics_message}\n\n{financial_message}",
                        reply_markup=keyboard
                    )
                    return
                
                # Формируем сообщение со статистикой
                stats_message = "📊 *Статистика вашего магазина на Ozon*\n\n"
                
                if financial_data:
                    # Получаем финансовую информацию из ответа API
                    try:
                        balance = financial_data.get("result", {}).get("balance", 0)
                        total_blocked = financial_data.get("result", {}).get("total_blocked", 0)
                        
                        stats_message += f"💰 *Финансы:*\n"
                        stats_message += f"- Баланс: `{balance} ₽`\n"
                        stats_message += f"- Заблокировано: `{total_blocked} ₽`\n\n"
                    except Exception as e:
                        stats_message += f"❌ Ошибка обработки финансовых данных: {str(e)}\n\n"
                
                if analytics_data:
                    # Получаем аналитическую информацию из ответа API
                    try:
                        stats_message += f"⭐ *Отзывы:*\n"
                        
                        # Получаем общую информацию из аналитики
                        if "result" in analytics_data and "data" in analytics_data["result"]:
                            comments_data = analytics_data["result"]["data"]
                            
                            # Суммируем данные по всем товарам
                            total_comments = 0
                            total_negative = 0
                            total_items = 0
                            avg_rating = 0
                            
                            for item in comments_data:
                                if "metrics" in item and "dimensions" in item:
                                    total_items += 1
                                    comments = item["metrics"].get("comments_count", 0)
                                    negative = item["metrics"].get("negative_comments_count", 0)
                                    rating = item["metrics"].get("rating", 0)
                                    
                                    total_comments += comments
                                    total_negative += negative
                                    avg_rating += rating
                            
                            if total_items > 0:
                                avg_rating = avg_rating / total_items
                                
                                stats_message += f"- Всего отзывов: `{total_comments}`\n"
                                stats_message += f"- Негативных отзывов: `{total_negative}`\n"
                                stats_message += f"- Средний рейтинг: `{avg_rating:.1f}⭐`\n\n"
                            else:
                                stats_message += "- Нет данных по отзывам\n\n"
                        else:
                            stats_message += "- Нет данных по отзывам\n\n"
                    except Exception as e:
                        stats_message += f"❌ Ошибка обработки аналитических данных: {str(e)}\n\n"
                
                # Добавляем ссылку на веб-интерфейс
                stats_message += "Для подробной статистики используйте веб-интерфейс."
                
                await bot.send_message(
                    chat_id=chat_id,
                    text=stats_message,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                
                # Добавляем кнопку для открытия приложения
                await bot.send_message(
                    chat_id=chat_id,
                    text="Открыть веб-интерфейс с подробной аналитикой:",
                    reply_markup=app_button
                )
                
            except Exception as e:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при получении статистики: {str(e)}",
                    reply_markup=keyboard
                )
        
        elif command == "verify":
            # Сбрасываем состояние пользователя
            if user_id in user_states:
                del user_states[user_id]
                
            user_token = get_user_token(user_id)
            
            if not user_token:
                await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Невозможно проверить токены. API токены не установлены.\n\n"
                         "Пожалуйста, используйте команду /set_token для установки токенов Ozon API.",
                    reply_markup=keyboard
                )
                return
            
            await bot.send_message(
                chat_id=chat_id,
                text="🔄 Проверяю валидность токенов через API Ozon...",
                reply_markup=keyboard
            )
            
            # Проверяем токены
            is_valid, message = await verify_ozon_tokens(user_token.ozon_api_token, user_token.ozon_client_id)
            
            if is_valid:
                await bot.send_message(
                    chat_id=chat_id,
                    text="✅ Ваши токены API Ozon действительны и работают корректно!\n\n"
                         f"Client ID: `{user_token.ozon_client_id}`\n"
                         f"API Token: `{user_token.ozon_api_token[:5]}...{user_token.ozon_api_token[-5:]}`",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка проверки токенов.\n\n{message}\n\n"
                         "Возможно, ваши токены устарели или были отозваны. "
                         "Пожалуйста, используйте команду /set_token для обновления токенов.",
                    reply_markup=keyboard
                )
        
        else:
            # Сбрасываем состояние пользователя при неизвестной команде
            if user_id in user_states:
                del user_states[user_id]
                
            await bot.send_message(
                chat_id=chat_id,
                text="🤔 Неизвестная команда. Используйте /help для получения списка доступных команд.",
                reply_markup=keyboard
            )
    except Exception as e:
        print(f"Ошибка при обработке команды {command}: {str(e)}")
        if chat_id:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Произошла ошибка при обработке команды: {str(e)}",
                reply_markup=get_main_keyboard()
            )

# Функция для обработки текстовых сообщений (не команд)
async def handle_message(update_data):
    """Обрабатывает обычные текстовые сообщения от пользователя"""
    try:
        chat_id = update_data.get("chat", {}).get("id")
        user_id = update_data.get("from", {}).get("id")
        username = update_data.get("from", {}).get("username", "пользователь")
        first_name = update_data.get("from", {}).get("first_name", username)
        text = update_data.get("text", "")
        
        # Создаем клавиатуру с кнопками
        keyboard = get_main_keyboard()
        # Создаем инлайн клавиатуру с кнопкой приложения
        app_button = get_app_button()
        
        # Если пользователя нет в состояниях, значит это обычное сообщение
        if user_id not in user_states:
            await bot.send_message(
                chat_id=chat_id,
                text="Я не понимаю ваше сообщение. Пожалуйста, используйте кнопки или команды для взаимодействия со мной.",
                reply_markup=keyboard
            )
            return
        
        # Обрабатываем сообщение в зависимости от состояния пользователя
        user_state = user_states[user_id]
        
        if user_state["state"] == "waiting_for_api_token":
            # Сохраняем API токен и запрашиваем Client ID
            api_token = text.strip()
            
            # Очищаем токен от возможных кавычек, пробелов и других символов
            api_token = api_token.replace('"', '').replace("'", "").strip()
            
            # Более гибкая проверка формата API токена
            if not api_token:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Пожалуйста, отправьте ваш API токен.",
                    reply_markup=keyboard
                )
                return
            
            # Минимальная длина для токена
            if len(api_token) < 8:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Токен слишком короткий. Пожалуйста, проверьте API токен и отправьте его снова.\n\n"
                         "API токен должен выглядеть примерно так: `ab12c3defghijk4lm5nop`",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                return
            
            # Сохраняем API токен и переходим к запросу Client ID
            user_states[user_id] = {
                "state": "waiting_for_client_id",
                "api_token": api_token
            }
            
            await bot.send_message(
                chat_id=chat_id,
                text="✅ API токен получен.\n\n"
                     "*Шаг 2:* Теперь пришлите мне ваш Client ID.\n"
                     "Это обычно числовое значение, например `12345`.\n\n"
                     "Просто скопируйте и отправьте Client ID из личного кабинета Ozon.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        
        elif user_state["state"] == "waiting_for_client_id":
            # Сохраняем Client ID и завершаем процесс
            client_id = text.strip()
            api_token = user_state["api_token"]
            
            # Очищаем client_id от возможных символов
            client_id = client_id.replace('"', '').replace("'", "").strip()
            
            # Проверяем на наличие только цифр (удаляем все нецифровые символы)
            client_id_cleaned = ''.join(char for char in client_id if char.isdigit())
            
            if not client_id_cleaned:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Не найдено числовое значение в вашем сообщении.\n\n"
                         "Client ID должен содержать числа. Пожалуйста, проверьте ID и отправьте его снова.",
                    reply_markup=keyboard
                )
                return
            
            # Используем очищенный client_id
            client_id = client_id_cleaned
            
            # Создаем объект с токенами
            user_token = UserToken(
                telegram_id=user_id,
                username=username,
                ozon_api_token=api_token,
                ozon_client_id=client_id
            )
            
            # Проверяем токены через API Ozon
            await bot.send_message(
                chat_id=chat_id,
                text="🔄 Проверяю валидность токенов через API Ozon...",
                reply_markup=keyboard
            )
            
            is_valid, message = await verify_ozon_tokens(api_token, client_id)
            
            if not is_valid:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка проверки токенов.\n\n{message}\n\n"
                         f"API токен: `{api_token[:5]}...{api_token[-5:]}`\n"
                         f"Client ID: `{client_id}`\n\n"
                         "Пожалуйста, проверьте токены и попробуйте еще раз с командой /set_token.",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                # Удаляем состояние пользователя из-за ошибки
                del user_states[user_id]
                return
            
            # Сохраняем токены если они валидны
            save_user_token(user_token)
            
            # Удаляем состояние пользователя, так как процесс завершен
            del user_states[user_id]
            
            await bot.send_message(
                chat_id=chat_id,
                text="✅ Токены API Ozon успешно проверены и сохранены!\n\n"
                     f"API токен: `{api_token[:5]}...{api_token[-5:]}`\n"
                     f"Client ID: `{client_id}`\n\n"
                     "Теперь вы можете использовать веб-интерфейс для анализа данных вашего магазина Ozon.\n"
                     "Ваши токены надежно сохранены и будут использоваться для авторизации API запросов.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            # Добавляем кнопку для открытия приложения после сохранения токенов
            await bot.send_message(
                chat_id=chat_id,
                text="Нажмите кнопку ниже, чтобы открыть веб-интерфейс с вашими данными:",
                reply_markup=app_button
            )
    
    except Exception as e:
        print(f"Ошибка при обработке сообщения: {str(e)}")
        if chat_id:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Произошла ошибка при обработке сообщения: {str(e)}",
                reply_markup=keyboard
            )

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Обрабатывает вебхуки от телеграм бота"""
    try:
        update_data = await request.json()
        
        # Проверяем, есть ли сообщение в обновлении
        if "message" not in update_data:
            return {"status": "success", "message": "Не является текстовым сообщением"}
        
        message = update_data["message"]
        
        # Проверяем наличие текста в сообщении
        if "text" not in message or not message["text"]:
            return {"status": "success", "message": "Сообщение без текста пропущено"}
        
        # Получаем текст сообщения и информацию о пользователе
        text = message["text"]
        user_id = message["from"]["id"]
        
        # Проверяем команды, начинающиеся с /
        if text.startswith("/"):
            # Извлекаем команду (без символа /)
            command = text.split()[0][1:]
            await handle_command(command, message)
            return {"status": "success"}
        
        # Обрабатываем текстовые кнопки
        command_map = {
            "Запустить бота 🚀": "start",
            "Помощь ❓": "help",
            "Установить токены 🔑": "set_token",
            "Проверить статус ℹ️": "status",
            "Статистика 📊": "stats",
            "Удалить токены ❌": "delete_tokens"
        }
        
        if text in command_map:
            await handle_command(command_map[text], message)
            return {"status": "success"}
        
        # Если это не команда и не кнопка, обрабатываем как обычное сообщение
        # (например, для ввода токенов)
        await handle_message(message)
        
        return {"status": "success"}
    except Exception as e:
        print(f"Ошибка обработки вебхука: {str(e)}")
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
        
        # Отправляем запрос
        response = requests.post(url, headers=headers, json=payload)
        
        # Проверяем статус ответа
        if response.status_code == 200:
            return True, "Токены действительны"
        
        error_message = f"Ошибка при проверке токенов: {response.status_code} - {response.text}"
        return False, error_message
    
    except Exception as e:
        error_message = f"Ошибка при проверке токенов: {str(e)}"
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
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
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