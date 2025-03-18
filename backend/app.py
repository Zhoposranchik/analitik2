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

# Настройки Telegram бота (можно будет обновлять через API)
BOT_TOKEN = "7576660819:AAH0RHDk5_9TQM386wk7zh9UofQlg3QB6mc"
CHAT_ID = "254918256"  # Узнай через @userinfobot

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

# Задачи, выполняющиеся в фоновом режиме
async def send_notification(chat_id: str, message: str):
    """Отправляет уведомление в телеграм"""
    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Ошибка отправки уведомления: {str(e)}")

# Функция для поиска токенов по телеграм ID пользователя
def get_user_by_telegram_id(telegram_id: int) -> dict:
    """Получает токены API для пользователя Telegram"""
    for user_hash, user_data in users_db.items():
        # Проверяем, есть ли привязка к данному telegram_id
        if user_data.get("telegram_id") == telegram_id:
            return {
                "user_hash": user_hash,
                "api_key": user_data.get("api_key"),
                "tokens": decrypt_tokens(user_data["tokens"]),
                "created_at": user_data.get("created_at")
            }
    return None

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
    # Данный эндпоинт будет принимать сообщения от пользователей телеграм
    # и отправлять команды боту для управления API токенами
    try:
        data = await request.json()
    except Exception as e:
        return {"status": "error", "message": f"Ошибка чтения JSON: {str(e)}"}
    
    try:
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        username = message.get("from", {}).get("username")
        text = message.get("text", "")
        
        if not chat_id or not user_id:
            return {"status": "error", "message": "Неверный формат данных"}
        
        # Регистрируем пользователя если его нет в базе
        if str(user_id) not in telegram_users_db:
            telegram_users_db[str(user_id)] = {
                "username": username,
                "chat_id": chat_id,
                "registered_at": datetime.now().isoformat()
            }
        
        # Обрабатываем команды
        if text.startswith("/start"):
            await bot.send_message(
                chat_id=chat_id,
                text="Добро пожаловать в Ozon Bot! Для начала работы необходимо установить API токены Ozon. Используйте команду /set_token."
            )
        elif text.startswith("/set_token"):
            # Команда для установки API токена
            # Формат: /set_token ozon_api_token ozon_client_id
            parts = text.split()
            if len(parts) == 3:
                ozon_api_token = parts[1]
                ozon_client_id = parts[2]
                
                # Создаем токены
                tokens = ApiTokens(
                    ozon_api_token=ozon_api_token,
                    ozon_client_id=ozon_client_id,
                    telegram_chat_id=str(chat_id)
                )
                
                # Генерируем API ключ
                api_key = f"tg-{user_id}-{datetime.now().timestamp()}"
                user_hash = hashlib.sha256(api_key.encode()).hexdigest()
                
                # Шифруем и сохраняем токены
                encrypted_tokens = encrypt_tokens(tokens.dict())
                users_db[user_hash] = {
                    "tokens": encrypted_tokens,
                    "created_at": datetime.now().isoformat(),
                    "telegram_id": user_id,
                    "api_key": api_key
                }
                
                # Сохраняем информацию о токенах в данных пользователя телеграм
                telegram_users_db[str(user_id)]["api_key"] = api_key
                
                await bot.send_message(
                    chat_id=chat_id,
                    text="API токены Ozon успешно сохранены! Теперь вы можете использовать веб-приложение."
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Неверный формат команды. Используйте: /set_token YOUR_API_TOKEN YOUR_CLIENT_ID"
                )
        elif text.startswith("/status"):
            # Показать статус API токенов
            user_data = get_user_by_telegram_id(user_id)
            if user_data:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"Ваши API токены активны. Последнее обновление: {user_data['created_at']}"
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="У вас нет активных API токенов. Используйте команду /set_token для установки."
                )
        elif text.startswith("/delete_tokens"):
            # Удалить API токены
            user_data = get_user_by_telegram_id(user_id)
            if user_data:
                user_hash = user_data["user_hash"]
                if user_hash in users_db:
                    del users_db[user_hash]
                    if str(user_id) in telegram_users_db:
                        telegram_users_db[str(user_id)].pop("api_key", None)
                    await bot.send_message(
                        chat_id=chat_id,
                        text="Ваши API токены успешно удалены."
                    )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="У вас нет активных API токенов."
                )
        elif text.startswith("/help"):
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "Доступные команды:\n"
                    "/start - начать работу с ботом\n"
                    "/set_token OZON_API_TOKEN OZON_CLIENT_ID - установить API токены\n"
                    "/status - проверить статус API токенов\n"
                    "/delete_tokens - удалить API токены\n"
                    "/help - показать эту справку"
                )
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="Неизвестная команда. Используйте /help для получения списка доступных команд."
            )
        
        return {"status": "success"}
    except Exception as e:
        print(f"Ошибка обработки вебхука: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/telegram/user/{user_id}/tokens")
async def get_telegram_user_tokens(user_id: int):
    """Получает API токены пользователя Telegram"""
    user_data = get_user_by_telegram_id(user_id)
    
    if not user_data:
        return {"message": "Пользователь не найден или не установлены API токены"}
    
    return {
        "tokens": user_data["tokens"],
        "api_key": user_data["api_key"]
    }

@app.get("/telegram/users")
async def get_telegram_users():
    """Получает список пользователей Telegram (только для админа)"""
    return {"users": telegram_users_db}