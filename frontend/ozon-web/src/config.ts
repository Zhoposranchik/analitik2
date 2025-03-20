// API URL для разных окружений

// Определяем базовый URL в зависимости от окружения
const API_BASE_URL = process.env.NODE_ENV === 'production'
  ? 'https://ozon-bot-api.onrender.com' // URL вашего бэкенда на Render
  : 'http://localhost:8000'; // Локальный URL для разработки

export const API_URL = API_BASE_URL;

// Другие настройки конфигурации
export const APP_VERSION = '1.0.0'; 