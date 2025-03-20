# Фронтенд Ozon Bot

Веб-интерфейс для взаимодействия с API Ozon Bot.

## Структура проекта

- `ozon-web/` - React-приложение для работы с API Ozon
  - `src/` - исходный код приложения
  - `public/` - статические файлы
  - `build/` - скомпилированная версия приложения для продакшена

## Локальная разработка

1. Перейдите в директорию приложения:
```bash
cd ozon-web
```

2. Установите зависимости:
```bash
npm install
```

3. Запустите приложение в режиме разработки:
```bash
npm start
```

Приложение будет доступно по адресу [http://localhost:3000](http://localhost:3000).

## Деплой на GitHub Pages

### Автоматический деплой через GitHub Actions

Настроен автоматический деплой при пуше в ветки `main` или `deploy`. 
Для триггера деплоя вручную:

1. Перейдите на GitHub в раздел Actions
2. Выберите workflow "Deploy Frontend to GitHub Pages"
3. Нажмите "Run workflow"

### Ручной деплой

1. Установите зависимости:
```bash
npm install
```

2. Запустите команду деплоя:
```bash
npm run deploy
```

## Конфигурация API

Для изменения URL API откройте файл `src/config.ts` и обновите значение `API_BASE_URL`:

```typescript
const API_BASE_URL = process.env.NODE_ENV === 'production'
  ? 'https://ваш-бэкенд-на-render.com' // URL вашего бэкенда на Render
  : 'http://localhost:8000'; // Локальный URL для разработки
``` 