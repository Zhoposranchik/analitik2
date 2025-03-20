import os
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import DictCursor

# Получаем URL базы данных из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Создает подключение к базе данных"""
    if DATABASE_URL:
        # Для PostgreSQL
        return psycopg2.connect(DATABASE_URL)
    else:
        # Для локальной разработки с SQLite
        return sqlite3.connect('user_tokens.db')

@contextmanager
def get_db():
    """Контекстный менеджер для работы с базой данных"""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Инициализирует базу данных"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Создаем таблицу для токенов пользователей
        if isinstance(conn, sqlite3.Connection):
            # SQLite
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
        else:
            # PostgreSQL
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_tokens (
                    user_id SERIAL PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    ozon_api_token TEXT,
                    ozon_client_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        conn.commit() 