from celery import Celery
from celery.schedules import crontab
import os
from dotenv import load_dotenv
import httpx
from datetime import datetime

# Загружаем переменные окружения
load_dotenv()

# Получаем URL бэкенда из переменных окружения или используем локальный хост
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Настройка Celery
app = Celery('ozon_bot_tasks')

# Конфигурация Celery
app.conf.broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
app.conf.result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Настройка часового пояса
app.conf.timezone = 'Europe/Moscow'

# Настройка периодических задач
app.conf.beat_schedule = {
    # Ежедневное обновление данных в 02:00
    'daily-data-update': {
        'task': 'celery_app.update_all_users_data',
        'schedule': crontab(hour=2, minute=0),
    },
    # Ежедневный отчет в 09:00
    'daily-report': {
        'task': 'celery_app.send_daily_reports',
        'schedule': crontab(hour=9, minute=0),
    },
    # Проверка метрик каждые 3 часа
    'check-metrics': {
        'task': 'celery_app.check_metrics',
        'schedule': crontab(minute=0, hour='*/3'),
    },
}

@app.task(name='celery_app.update_all_users_data')
def update_all_users_data():
    """Задача для обновления данных всех пользователей"""
    try:
        # Вызываем API endpoint для обновления данных
        response = httpx.post(f"{BACKEND_URL}/api/update_all_data", timeout=300)
        
        if response.status_code == 200:
            print(f"[{datetime.now()}] Данные всех пользователей успешно обновлены")
            return {"status": "success", "message": "Данные всех пользователей успешно обновлены"}
        else:
            print(f"[{datetime.now()}] Ошибка при обновлении данных: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"Ошибка при обновлении данных: {response.status_code}"}
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка при выполнении задачи update_all_users_data: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.task(name='celery_app.send_daily_reports')
def send_daily_reports():
    """Задача для отправки ежедневных отчетов"""
    try:
        # Вызываем API endpoint для отправки отчетов
        response = httpx.get(f"{BACKEND_URL}/api/send_daily_reports", timeout=120)
        
        if response.status_code == 200:
            print(f"[{datetime.now()}] Ежедневные отчеты успешно отправлены")
            return {"status": "success", "message": "Ежедневные отчеты успешно отправлены"}
        else:
            print(f"[{datetime.now()}] Ошибка при отправке отчетов: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"Ошибка при отправке отчетов: {response.status_code}"}
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка при выполнении задачи send_daily_reports: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.task(name='celery_app.check_metrics')
def check_metrics():
    """Задача для проверки метрик и отправки уведомлений"""
    try:
        # Вызываем API endpoint для проверки метрик
        response = httpx.get(f"{BACKEND_URL}/api/check_metrics", timeout=120)
        
        if response.status_code == 200:
            print(f"[{datetime.now()}] Проверка метрик успешно выполнена")
            return {"status": "success", "message": "Проверка метрик успешно выполнена"}
        else:
            print(f"[{datetime.now()}] Ошибка при проверке метрик: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"Ошибка при проверке метрик: {response.status_code}"}
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка при выполнении задачи check_metrics: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.task(name='celery_app.update_user_data')
def update_user_data(user_id):
    """Задача для обновления данных конкретного пользователя"""
    try:
        # Вызываем API endpoint для обновления данных пользователя
        response = httpx.post(
            f"{BACKEND_URL}/api/update_data", 
            json={"user_id": user_id},
            timeout=120
        )
        
        if response.status_code == 200:
            print(f"[{datetime.now()}] Данные пользователя {user_id} успешно обновлены")
            return {"status": "success", "message": f"Данные пользователя {user_id} успешно обновлены"}
        else:
            print(f"[{datetime.now()}] Ошибка при обновлении данных пользователя {user_id}: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"Ошибка при обновлении данных: {response.status_code}"}
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка при выполнении задачи update_user_data для пользователя {user_id}: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == '__main__':
    app.start() 