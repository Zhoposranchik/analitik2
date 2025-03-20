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
from telegram import Update

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
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
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

# Обработчики команд Telegram бота
async def handle_command(command, update_data):
    """Обрабатывает команды от Telegram"""
    try:
        chat_id = update_data.get("chat", {}).get("id")
        user_id = update_data.get("from", {}).get("id")
        username = update_data.get("from", {}).get("username", "пользователь")
        text = update_data.get("text", "")
        
        if command == "start":
            await bot.send_message(
                chat_id=chat_id,
                text=f"Привет, {username}! Я бот для работы с API Ozon.\n\n"
                     f"Доступные команды:\n"
                     f"/set_token OZON_API_TOKEN OZON_CLIENT_ID - установить API токены\n"
                     f"/status - проверить статус API токенов\n"
                     f"/delete_tokens - удалить API токены\n"
                     f"/help - показать справку"
            )
        elif command == "set_token":
            # Получаем аргументы команды
            args = text.split()
            if len(args) != 3:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Использование: /set_token OZON_API_TOKEN OZON_CLIENT_ID"
                )
                return

            ozon_api_token = args[1]
            ozon_client_id = args[2]

            # Сохраняем токены
            user_token = UserToken(
                telegram_id=user_id,
                username=username,
                ozon_api_token=ozon_api_token,
                ozon_client_id=ozon_client_id
            )
            save_user_token(user_token)

            await bot.send_message(
                chat_id=chat_id,
                text="✅ API токены успешно сохранены!"
            )
        elif command == "status":
            user_token = get_user_token(user_id)
            
            if user_token:
                await bot.send_message(
                    chat_id=chat_id,
                    text="✅ API токены установлены\n"
                         f"Username: {user_token.username}\n"
                         f"Client ID: {user_token.ozon_client_id[:5]}...\n"
                         f"API Token: {user_token.ozon_api_token[:5]}..."
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="❌ API токены не установлены. Используйте /set_token для установки."
                )
        elif command == "delete_tokens":
            delete_user_token(user_id)
            
            await bot.send_message(
                chat_id=chat_id,
                text="✅ API токены успешно удалены"
            )
        elif command == "help":
            await bot.send_message(
                chat_id=chat_id,
                text="🤖 Справка по командам:\n\n"
                     f"/start - начать работу с ботом\n"
                     f"/set_token OZON_API_TOKEN OZON_CLIENT_ID - установить API токены\n"
                     f"/status - проверить статус API токенов\n"
                     f"/delete_tokens - удалить API токены\n"
                     f"/help - показать эту справку"
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="Неизвестная команда. Используйте /help для получения списка доступных команд."
            )
    except Exception as e:
        print(f"Ошибка при обработке команды {command}: {str(e)}")
        if chat_id:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Произошла ошибка при обработке команды: {str(e)}"
            )

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
async def get_products(period: str = "month", api_key: Optional[str] = None):
    """Получает список товаров с опциональной фильтрацией по периоду"""
    # В реальном приложении здесь будет запрос к API Ozon с использованием токенов пользователя
    
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
async def get_analytics(period: str = "month", api_key: Optional[str] = None):
    """Получает аналитику по товарам за период"""
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

# Новые эндпоинты для интеграции с Telegram

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Обрабатывает вебхуки от телеграм бота"""
    try:
        data = await request.json()
        
        # Получаем сообщение
        message = data.get("message", {})
        if not message:
            return {"status": "error", "message": "Сообщение не найдено"}
        
        # Получаем текст сообщения
        text = message.get("text", "")
        if not text:
            return {"status": "success", "message": "Сообщение без текста пропущено"}
        
        # Обрабатываем команды
        if text.startswith("/"):
            # Извлекаем команду (без символа /)
            command = text.split()[0][1:]
            await handle_command(command, message)
        
        return {"status": "success"}
    except Exception as e:
        print(f"Ошибка обработки вебхука: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/telegram/user/{user_id}/tokens")
async def get_telegram_user_tokens(user_id: int):
    """Получает API токены пользователя Telegram"""
    user_token = get_user_token(user_id)
    
    if not user_token:
        return {"message": "Пользователь не найден или не установлены API токены"}
    
    return {
        "tokens": user_token.dict(),
        "created_at": user_token.created_at
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
        # Здесь должен быть публичный URL вашего приложения
        webhook_url = "https://your-domain.com/telegram/webhook"
        
        # Для локальной разработки можно использовать ngrok или аналогичный сервис
        # webhook_url = "https://your-ngrok-url.ngrok.io/telegram/webhook"
        
        print(f"Настройка вебхука: {webhook_url}")
        # Закомментировано до готовности публичного URL
        # await bot.set_webhook(webhook_url)
        print("⚠️ Вебхук не настроен - для работы используйте ручное тестирование через эндпоинт /telegram/webhook")
    except Exception as e:
        print(f"Ошибка настройки вебхука: {str(e)}")

# Запускаем настройку вебхука при старте приложения
@app.on_event("startup")
async def startup_event():
    """Запускает настройку вебхука при старте приложения"""
    # await setup_webhook()
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