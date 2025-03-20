import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { API_URL } from './config';
// Импортируем Telegram WebApp API

// Интерфейс для типизации продукта
interface Product {
  product_id: number;
  name: string;
  offer_id: string;
  price: number;
  cost: number;  // Себестоимость товара
  images: string[];
}

// Интерфейс для токенов API
interface ApiTokens {
  ozon_api_token: string;
  ozon_client_id: string;
  telegram_bot_token?: string;
  telegram_chat_id?: string;
}

// Функция "шифрования" токенов (в реальном приложении требуется использовать настоящее шифрование)
const encryptTokens = (tokens: ApiTokens): string => {
  // Это упрощенная версия, в продакшене использовать настоящее шифрование
  return window.btoa(JSON.stringify(tokens));
};

// Функция "дешифрования" токенов
const decryptTokens = (encryptedTokens: string): ApiTokens => {
  try {
    // Это упрощенная версия, в продакшене использовать настоящее дешифрование
    return JSON.parse(window.atob(encryptedTokens));
  } catch (error) {
    console.error('Ошибка при дешифровании токенов:', error);
    return {
      ozon_api_token: '',
      ozon_client_id: '',
      telegram_bot_token: '',
      telegram_chat_id: ''
    };
  }
};

// Импортируем типы для Chart.js (используется для типизации в компонентах диаграмм)
interface ChartData {
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
    backgroundColor?: string | string[];
  }>;
}

// Компонент для отображения графика продаж
const SalesChart = ({ data }: { data: number[] }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  useEffect(() => {
    if (!canvasRef.current) return;
    
    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return;
    
    // Очищаем canvas перед рисованием
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    
    // Определяем параметры графика
    const width = canvasRef.current.width;
    const height = canvasRef.current.height;
    const padding = 40;
    const chartWidth = width - 2 * padding;
    const chartHeight = height - 2 * padding;
    
    // Находим максимальное значение для масштабирования
    const maxValue = Math.max(...data, 1);
    
    // Рисуем оси
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.strokeStyle = '#ccc';
    ctx.stroke();
    
    // Рисуем подписи по оси Y
    ctx.fillStyle = '#666';
    ctx.font = '12px Arial';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    
    for (let i = 0; i <= 4; i++) {
      const y = height - padding - (i * chartHeight / 4);
      const value = Math.round(maxValue * i / 4);
      ctx.fillText(`${value} ₽`, padding - 5, y);
      
      // Рисуем горизонтальные линии сетки
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.strokeStyle = '#eee';
      ctx.stroke();
    }
    
    // Ширина каждого столбца
    const barWidth = chartWidth / data.length - 10;
    
    // Рисуем столбцы
    data.forEach((value, index) => {
      const x = padding + index * (chartWidth / data.length) + 5;
      const barHeight = (value / maxValue) * chartHeight;
      const y = height - padding - barHeight;
      
      // Градиент для столбца
      const gradient = ctx.createLinearGradient(x, y, x, height - padding);
      gradient.addColorStop(0, '#3498db');
      gradient.addColorStop(1, '#2980b9');
      
      ctx.fillStyle = gradient;
      ctx.fillRect(x, y, barWidth, barHeight);
      
      // Подписи по оси X (дни или месяцы)
      ctx.fillStyle = '#666';
      ctx.font = '10px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(`${index + 1}`, x + barWidth / 2, height - padding + 5);
    });
    
    // Заголовок графика
    ctx.fillStyle = '#333';
    ctx.font = 'bold 14px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('Продажи за период', width / 2, 10);
  }, [data]);
  
  return <canvas ref={canvasRef} width={300} height={200} />;
};

// Компонент для отображения графика маржинальности
const MarginChart = ({ data }: { data: number[] }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  useEffect(() => {
    if (!canvasRef.current) return;
    
    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return;
    
    // Очищаем canvas перед рисованием
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    
    // Определяем параметры графика
    const width = canvasRef.current.width;
    const height = canvasRef.current.height;
    const padding = 40;
    const chartWidth = width - 2 * padding;
    const chartHeight = height - 2 * padding;
    
    // Находим максимальное значение для масштабирования (не меньше 50%)
    const maxValue = Math.max(50, Math.max(...data));
    
    // Рисуем оси
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.strokeStyle = '#ccc';
    ctx.stroke();
    
    // Рисуем подписи по оси Y
    ctx.fillStyle = '#666';
    ctx.font = '12px Arial';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    
    for (let i = 0; i <= 4; i++) {
      const y = height - padding - (i * chartHeight / 4);
      const value = Math.round(maxValue * i / 4);
      ctx.fillText(`${value}%`, padding - 5, y);
      
      // Рисуем горизонтальные линии сетки
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.strokeStyle = '#eee';
      ctx.stroke();
    }
    
    // Рисуем линию маржинальности
    ctx.beginPath();
    data.forEach((value, index) => {
      const x = padding + index * (chartWidth / (data.length - 1));
      const y = height - padding - (value / maxValue) * chartHeight;
      
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    ctx.strokeStyle = '#2ecc71';
    ctx.lineWidth = 3;
    ctx.stroke();
    
    // Создаем градиент под линией
    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, 'rgba(46, 204, 113, 0.4)');
    gradient.addColorStop(1, 'rgba(46, 204, 113, 0.1)');
    
    // Заполняем область под линией
    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    
    // Подписи по оси X
    ctx.fillStyle = '#666';
    ctx.font = '10px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    
    data.forEach((_, index) => {
      const x = padding + index * (chartWidth / (data.length - 1));
      ctx.fillText(`${index + 1}`, x, height - padding + 5);
    });
    
    // Заголовок графика
    ctx.fillStyle = '#333';
    ctx.font = 'bold 14px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('Маржинальность, %', width / 2, 10);
  }, [data]);
  
  return <canvas ref={canvasRef} width={300} height={200} />;
};

// Компонент для отображения графика ROI
const ROIChart = ({ data }: { data: number[] }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  useEffect(() => {
    if (!canvasRef.current) return;
    
    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return;
    
    // Очищаем canvas перед рисованием
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    
    // Определяем параметры графика
    const width = canvasRef.current.width;
    const height = canvasRef.current.height;
    const padding = 40;
    const chartWidth = width - 2 * padding;
    const chartHeight = height - 2 * padding;
    
    // Находим максимальное значение для масштабирования (не меньше 100%)
    const maxValue = Math.max(100, Math.max(...data));
    
    // Рисуем оси
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.strokeStyle = '#ccc';
    ctx.stroke();
    
    // Рисуем подписи по оси Y
    ctx.fillStyle = '#666';
    ctx.font = '12px Arial';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    
    for (let i = 0; i <= 4; i++) {
      const y = height - padding - (i * chartHeight / 4);
      const value = Math.round(maxValue * i / 4);
      ctx.fillText(`${value}%`, padding - 5, y);
      
      // Рисуем горизонтальные линии сетки
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.strokeStyle = '#eee';
      ctx.stroke();
    }
    
    // Рисуем линию ROI
    ctx.beginPath();
    data.forEach((value, index) => {
      const x = padding + index * (chartWidth / (data.length - 1));
      const y = height - padding - (value / maxValue) * chartHeight;
      
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    ctx.strokeStyle = '#9b59b6';
    ctx.lineWidth = 3;
    ctx.stroke();
    
    // Создаем градиент под линией
    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, 'rgba(155, 89, 182, 0.4)');
    gradient.addColorStop(1, 'rgba(155, 89, 182, 0.1)');
    
    // Заполняем область под линией
    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    
    // Подписи по оси X
    ctx.fillStyle = '#666';
    ctx.font = '10px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    
    data.forEach((_, index) => {
      const x = padding + index * (chartWidth / (data.length - 1));
      ctx.fillText(`${index + 1}`, x, height - padding + 5);
    });
    
    // Заголовок графика
    ctx.fillStyle = '#333';
    ctx.font = 'bold 14px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('ROI, %', width / 2, 10);
  }, [data]);
  
  return <canvas ref={canvasRef} width={300} height={200} />;
};

// Функция для проверки доступности API
const checkApiAvailability = async (): Promise<boolean> => {
  try {
    const response = await fetch(`${API_URL}/`);
    return response.ok;
  } catch (error) {
    console.error('API недоступен:', error);
    return false;
  }
};

// Функция для выполнения безопасных запросов к API с обработкой ошибок
const fetchApi = async (url: string, options?: RequestInit): Promise<any> => {
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Ошибка сервера: ${response.status} - ${errorText}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`Ошибка запроса к ${url}:`, error);
    // Если это ошибка сети (API недоступен), возвращаем специальный флаг
    if (error instanceof TypeError && error.message.includes('network')) {
      throw new Error('API_UNAVAILABLE');
    }
    throw error;
  }
};

function App() {
  // Telegram WebApp инициализация
  const initTelegramWebApp = () => {
    if (window.Telegram) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
    }
  };

  const [activeTab, setActiveTab] = useState('home');
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportStatus, setReportStatus] = useState<string | null>(null);
  const [telegramUser, setTelegramUser] = useState<{id: number, username?: string} | null>(null);
  const [isApiAvailable, setIsApiAvailable] = useState<boolean>(false);
  const [isDarkTheme, setIsDarkTheme] = useState<boolean>(() => {
    // Проверяем сохраненные настройки темы или используем системные настройки
    const savedTheme = localStorage.getItem('darkTheme');
    if (savedTheme !== null) {
      return savedTheme === 'true';
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });
  
  // Переключатель темы
  const toggleTheme = () => {
    const newTheme = !isDarkTheme;
    setIsDarkTheme(newTheme);
    localStorage.setItem('darkTheme', String(newTheme));
  };

  // Применяем класс темы к body
  useEffect(() => {
    if (isDarkTheme) {
      document.body.classList.add('dark-theme');
    } else {
      document.body.classList.remove('dark-theme');
    }
  }, [isDarkTheme]);
  
  // Состояния для токенов API и настроек
  const [apiTokens, setApiTokens] = useState<ApiTokens>(() => {
    const savedTokens = localStorage.getItem('encryptedTokens');
    if (savedTokens) {
      return decryptTokens(savedTokens);
    }
    return {
      ozon_api_token: '',
      ozon_client_id: '',
      telegram_bot_token: '',
      telegram_chat_id: ''
    };
  });
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(
    Boolean(apiTokens.ozon_api_token && apiTokens.ozon_client_id)
  );
  const [notificationThreshold, setNotificationThreshold] = useState<number>(15); // Порог маржинальности в %
  const [selectedPeriod, setSelectedPeriod] = useState<string>('month'); // По умолчанию - месяц

  // Состояния для данных аналитики
  const [analyticsData, setAnalyticsData] = useState({
    sales: 0,
    margin: 0,
    roi: 0,
    profit: 0,
    total_products: 0,
    active_products: 0,
    orders: 0,
    average_order: 0,
    marketplace_fees: 0,
    advertising_costs: 0,
    sales_data: [] as number[],
    margin_data: [] as number[],
    roi_data: [] as number[]
  });

  // Функции для расчетов
  const calculateMargin = (price: number, cost: number): number => {
    if (cost === 0) return 0;
    return ((price - cost) / price) * 100;
  };
  
  const calculateROI = (price: number, cost: number): number => {
    if (cost === 0) return 0;
    return ((price - cost) / cost) * 100;
  };

  // Состояние для себестоимости товаров
  const [productCosts, setProductCosts] = useState<Array<{product_id: number, cost: number}>>([]);

  // Функция для получения аналитики с API
  const fetchAnalytics = () => {
    if (!isApiAvailable) {
      setError('API сервер недоступен. Невозможно получить данные аналитики.');
      return Promise.reject(new Error('API_UNAVAILABLE'));
    }
    
    if (!isAuthenticated && !telegramUser) {
      setError('Необходимо авторизоваться через Telegram для получения данных.');
      return Promise.reject(new Error('NOT_AUTHENTICATED'));
    }
    
    const apiUrl = telegramUser 
      ? `${API_URL}/api/analytics?period=${selectedPeriod}&telegram_id=${telegramUser.id}`
      : `${API_URL}/analytics?period=${selectedPeriod}`;
    
    const headers: HeadersInit = telegramUser ? {} : {
      'X-API-Key': localStorage.getItem('apiKey') || ''
    };
    
    return fetchApi(apiUrl, { headers })
      .then(data => {
        setAnalyticsData(data);
        setError(null);
        return data;
      })
      .catch(err => {
        if (err.message === 'API_UNAVAILABLE') {
          setIsApiAvailable(false);
          setError('API сервер недоступен. Невозможно получить данные аналитики.');
        } else {
          console.error('Ошибка при получении аналитики:', err);
          setError('Ошибка при получении данных аналитики. Пожалуйста, попробуйте позже.');
        }
        throw err;
      });
  };

  // Функция для получения списка товаров с API
  const fetchProducts = () => {
    if (!isApiAvailable) {
      setError('API сервер недоступен. Невозможно получить список товаров.');
      return Promise.reject(new Error('API_UNAVAILABLE'));
    }
    
    if (!isAuthenticated && !telegramUser) {
      setError('Необходимо авторизоваться через Telegram для получения данных.');
      return Promise.reject(new Error('NOT_AUTHENTICATED'));
    }
    
    const apiUrl = telegramUser 
      ? `${API_URL}/api/products?period=${selectedPeriod}&telegram_id=${telegramUser.id}`
      : `${API_URL}/products?period=${selectedPeriod}`;
    
    const headers: HeadersInit = telegramUser ? {} : {
      'X-API-Key': localStorage.getItem('apiKey') || ''
    };
    
    return fetchApi(apiUrl, { headers })
      .then(data => {
        if (data && data.result && Array.isArray(data.result.items)) {
          const productsWithCosts = data.result.items.map((product: any) => {
            // Ищем сохраненную себестоимость для этого товара
            const savedCost = productCosts.find((pc: {product_id: number, cost: number}) => pc.product_id === product.product_id);
            
            return {
              ...product,
              cost: savedCost ? savedCost.cost : 0,
              margin: calculateMargin(product.price, savedCost ? savedCost.cost : 0),
              roi: calculateROI(product.price, savedCost ? savedCost.cost : 0)
            };
          });
          
          setProducts(productsWithCosts);
          setError(null);
          return productsWithCosts;
        } else {
          throw new Error('Неверный формат данных');
        }
      })
      .catch(err => {
        if (err.message === 'API_UNAVAILABLE') {
          setIsApiAvailable(false);
          setError('API сервер недоступен. Невозможно получить список товаров.');
        } else {
          console.error('Ошибка при получении списка товаров:', err);
          setError('Ошибка при получении списка товаров. Пожалуйста, попробуйте позже.');
        }
        throw err;
      });
  };

  // Функция для получения токенов API от бота
  const fetchUserTokensFromBot = (userId: number) => {
    setLoading(true);
    
    // Сохраняем Telegram ID в localStorage
    localStorage.setItem('telegramUserId', userId.toString());
    
    // Получаем токены от API бэкенда по ID пользователя Telegram
    fetchApi(`${API_URL}/api/auth/telegram/${userId}`)
      .then(data => {
        if (data && data.ozon_api_token && data.ozon_client_id) {
          const tokens: ApiTokens = {
            ozon_api_token: data.ozon_api_token,
            ozon_client_id: data.ozon_client_id,
            // Оставляем пустыми, так как их не нужно вводить в настройках
            telegram_bot_token: '',
            telegram_chat_id: ''
          };
          
          // Сохраняем API ключ в localStorage
          if (data.api_key) {
            localStorage.setItem('apiKey', data.api_key);
          }
          
          // Сохраняем токены
          saveTokens(tokens);
          setApiTokens(tokens);
          setIsAuthenticated(true);
          
          // Загружаем данные с API после успешной авторизации
          refreshData();
          
          setError(null);
        } else {
          setError('Токены API не найдены. Пожалуйста, введите токены в боте Telegram');
          setIsAuthenticated(false);
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('Ошибка при получении токенов:', err);
        if (err.response && err.response.status === 404) {
          setError('Пользователь не найден или не установлены API токены. Пожалуйста, настройте токены в боте Telegram.');
        } else if (err.response && err.response.status === 400) {
          setError('Токены недействительны или устарели. Пожалуйста, обновите их в боте Telegram.');
        } else {
          setError('Ошибка при получении токенов API. Пожалуйста, попробуйте позже.');
        }
        setIsAuthenticated(false);
        setLoading(false);
      });
  };
  
  // Получение данных пользователя Telegram и токенов API
  useEffect(() => {
    // Проверяем, работает ли Telegram API и доступен ли пользователь
    if (window.Telegram && window.Telegram.WebApp) {
      const webapp = window.Telegram.WebApp;
      const user = webapp.initDataUnsafe?.user;
      
      if (user) {
        // Сохраняем информацию о пользователе Telegram
        setTelegramUser({ id: user.id, username: user.username });
      
        // Получаем токены API для пользователя Telegram
        if (isApiAvailable) {
          fetchUserTokensFromBot(user.id);
        }
      }
    }
  }, [isApiAvailable]);

  // Проверка доступности API при загрузке приложения
  useEffect(() => {
    const checkApi = async () => {
      const isAvailable = await checkApiAvailability();
      setIsApiAvailable(isAvailable);
      if (!isAvailable) {
        setError('API сервер недоступен. Пожалуйста, проверьте подключение и перезагрузите страницу.');
      } else {
        // Инициализируем Telegram WebApp если возможно
        initTelegramWebApp();
        
        // Проверяем наличие сохраненного Telegram ID в localStorage
        const savedTelegramUserId = localStorage.getItem('telegramUserId');
        if (savedTelegramUserId) {
          // Если есть Telegram ID, но нет пользователя Telegram (не в WebApp)
          // то получаем токены по сохраненному ID
          if (!telegramUser) {
            fetchUserTokensFromBot(parseInt(savedTelegramUserId, 10));
          }
        }
      }
    };
    
    checkApi();
    
    // Устанавливаем интервал для периодической проверки доступности API
    const apiCheckInterval = setInterval(async () => {
      const isAvailable = await checkApiAvailability();
      if (isAvailable !== isApiAvailable) {
        setIsApiAvailable(isAvailable);
        if (isAvailable) {
          setError(null);
        } else {
          setError('API сервер недоступен. Пожалуйста, проверьте подключение и перезагрузите страницу.');
        }
      }
    }, 30000); // Проверяем каждые 30 секунд
    
    return () => clearInterval(apiCheckInterval);
  }, []);

  useEffect(() => {
    if (activeTab === 'products' && isApiAvailable) {
      setLoading(true);
      setError(null);
      
      // Получаем API ключ
      const apiKey = localStorage.getItem('apiKey');
      
      fetchApi(`${API_URL}/products`, {
        headers: {
          'X-API-Key': apiKey || ''
        }
      })
        .then(data => {
          if (data.result && Array.isArray(data.result.items)) {
            setProducts(data.result.items);
          } else {
            setProducts([]);
            console.warn('Неожиданный формат данных:', data);
          }
        })
        .catch(err => {
          if (err.message === 'API_UNAVAILABLE') {
            setIsApiAvailable(false);
            setError('API сервер недоступен. Работаем в оффлайн режиме с демо-данными.');
            // Используем тестовые данные
            const mockProducts = [
              {
                product_id: 123456,
                name: "Демо товар 1",
                offer_id: "DEMO-001",
                price: 1500,
                images: ["https://via.placeholder.com/150"],
                cost: 750
              },
              {
                product_id: 123457,
                name: "Демо товар 2",
                offer_id: "DEMO-002",
                price: 2500,
                images: ["https://via.placeholder.com/150"],
                cost: 1250
              }
            ];
            setProducts(mockProducts);
          } else {
            console.error('Ошибка при загрузке товаров:', err);
            setError(`Не удалось загрузить товары: ${err.message}`);
          }
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [activeTab, isApiAvailable]);

  useEffect(() => {
    if (activeTab === 'analytics' && isAuthenticated && isApiAvailable) {
      setLoading(true);
      setError(null);
      
      // Параметры запроса в зависимости от выбранного периода
      const params = new URLSearchParams({
        period: selectedPeriod
      });
      
      fetchApi(`${API_URL}/analytics?${params.toString()}`, {
        headers: {
          'X-API-Key': localStorage.getItem('apiKey') || ''
        }
      })
        .then(data => {
          console.log('Получены данные аналитики:', data);
          // Обновляем состояние аналитики
          setAnalyticsData({
            sales: data.sales || 0,
            margin: data.margin || 0,
            roi: data.roi || 0,
            profit: data.profit || 0,
            total_products: data.total_products || 0,
            active_products: data.active_products || 0,
            orders: data.orders || 0,
            average_order: data.average_order || 0,
            marketplace_fees: data.marketplace_fees || 0,
            advertising_costs: data.advertising_costs || 0,
            sales_data: data.sales_data || [15000, 18000, 22000, 24500, 20000, 23000, 24500],
            margin_data: data.margin_data || [18.5, 20.2, 22.8, 24.1, 23.5, 24.0, 23.5],
            roi_data: data.roi_data || [33.2, 38.5, 41.2, 43.7, 42.1, 42.5, 42.8]
          });
        })
        .catch(err => {
          if (err.message === 'API_UNAVAILABLE') {
            setIsApiAvailable(false);
            setError('API сервер недоступен. Работаем в оффлайн режиме с демо-данными.');
            // Используем тестовые данные аналитики
            setAnalyticsData({
              sales: 24500,
              margin: 23.5,
              roi: 42.8,
              profit: 8250,
              total_products: 36,
              active_products: 28,
              orders: 52,
              average_order: 3100,
              marketplace_fees: 3675,
              advertising_costs: 2200,
              sales_data: [15000, 18000, 22000, 24500, 20000, 23000, 24500],
              margin_data: [18.5, 20.2, 22.8, 24.1, 23.5, 24.0, 23.5],
              roi_data: [33.2, 38.5, 41.2, 43.7, 42.1, 42.5, 42.8]
            });
          } else {
            console.error('Ошибка при загрузке аналитики:', err);
            setError(`Не удалось загрузить аналитику: ${err.message}`);
          }
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [activeTab, selectedPeriod, isAuthenticated, isApiAvailable]);

  // Сохранение токенов в localStorage с "шифрованием"
  const saveTokens = (newTokens: ApiTokens) => {
    const encrypted = encryptTokens(newTokens);
    localStorage.setItem('encryptedTokens', encrypted);
    setApiTokens(newTokens);
    setIsAuthenticated(Boolean(newTokens.ozon_api_token && newTokens.ozon_client_id));
  };

  // Удаление токенов
  const removeTokens = () => {
    localStorage.removeItem('encryptedTokens');
    localStorage.removeItem('apiKey');
    setApiTokens({
      ozon_api_token: '',
      ozon_client_id: '',
      telegram_bot_token: '',
      telegram_chat_id: ''
    });
    setIsAuthenticated(false);
  };

  // Обработчик формы настроек - только для информации, настройки изменяются в боте
  const handleSettingsSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isApiAvailable) {
      alert('API сервер недоступен. Настройки можно будет изменить только после восстановления соединения с сервером.');
      return;
    }
    alert('Настройки Ozon API токена изменяются через Telegram бота. Пожалуйста, используйте команды бота для обновления токенов.');
  };

  const sendReport = () => {
    if (!isAuthenticated) {
      alert('Необходимо ввести API токен Ozon через Telegram бота');
      return;
    }
    
    if (!isApiAvailable) {
      alert('API сервер недоступен. Отправка отчета невозможна.');
      return;
    }
    
    setReportStatus('Отправка отчета...');
    
    fetchApi(`${API_URL}/send_report`, {
      headers: {
        'X-API-Key': localStorage.getItem('apiKey') || ''
      }
    })
      .then(data => {
        setReportStatus('Отчет успешно отправлен!');
        console.log('Ответ сервера:', data);
        
        // Через 3 секунды скрываем статус
        setTimeout(() => {
          setReportStatus(null);
        }, 3000);
      })
      .catch(err => {
        if (err.message === 'API_UNAVAILABLE') {
          setIsApiAvailable(false);
          setReportStatus('Ошибка: API сервер недоступен.');
        } else {
          console.error('Ошибка при отправке отчета:', err);
          setReportStatus(`Ошибка отправки: ${err.message}`);
        }
      });
  };

  // Компонент выбора периода
  const PeriodSelector = () => {
    const [isOpen, setIsOpen] = useState(false);
    
    const periods = [
      { id: 'day', label: 'День' },
      { id: 'week', label: 'Неделя' },
      { id: 'month', label: 'Месяц' },
      { id: 'year', label: 'Год' }
    ];
    
    const handleSelect = (period: string) => {
      setSelectedPeriod(period);
      setIsOpen(false);
    };
    
    return (
      <div className="period-selector">
        <div className="selected-period" onClick={() => setIsOpen(!isOpen)}>
          {periods.find(p => p.id === selectedPeriod)?.label || 'Месяц'} ▼
        </div>
        {isOpen && (
          <div className="period-dropdown">
            {periods.map(period => (
              <div 
                key={period.id} 
                className={`period-option ${selectedPeriod === period.id ? 'active' : ''}`}
                onClick={() => handleSelect(period.id)}
              >
                {period.label}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Обновление данных при изменении периода
  useEffect(() => {
    if (isAuthenticated || telegramUser) {
      refreshData();
    }
  }, [selectedPeriod]);
  
  // Функция для обновления всех данных
  const refreshData = () => {
    setLoading(true);
    
    // Получаем аналитику и товары (последовательно)
    fetchAnalytics()
      .then(() => fetchProducts())
      .then(() => {
        setLoading(false);
      })
      .catch(err => {
        console.error('Ошибка при обновлении данных:', err);
        setLoading(false);
      });
  };

  // Сохранение себестоимости товаров
  const saveCosts = () => {
    if (!isAuthenticated) {
      alert('Необходимо ввести API токен Ozon через Telegram бота');
      return;
    }
    
    if (!isApiAvailable) {
      alert('API сервер недоступен. Сохранение себестоимости возможно только в локальное хранилище.');
      // Сохраняем только локально
      const costsData = products.map(product => ({
        product_id: product.product_id,
        offer_id: product.offer_id,
        cost: product.cost || 0
      }));
      localStorage.setItem('productCosts', JSON.stringify(costsData));
      alert('Себестоимость товаров сохранена локально!');
      return;
    }
    
    const costsData = products.map(product => ({
      product_id: product.product_id,
      offer_id: product.offer_id,
      cost: product.cost || 0
    }));
    
    // Сохраняем в localStorage как временное резервное решение
    localStorage.setItem('productCosts', JSON.stringify(costsData));
    
    // Получаем API ключ из localStorage
    const apiKey = localStorage.getItem('apiKey');
    if (!apiKey) {
      alert('Ошибка: API ключ не найден');
      return;
    }
    
    // Попытка отправить данные на сервер
    fetchApi(`${API_URL}/products/costs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey
      },
      body: JSON.stringify(costsData)
    })
    .then(data => {
      alert('Себестоимость товаров успешно сохранена!');
      console.log('Ответ сервера:', data);
    })
    .catch(err => {
      if (err.message === 'API_UNAVAILABLE') {
        setIsApiAvailable(false);
        alert('API сервер недоступен. Себестоимость сохранена только локально.');
      } else {
        console.error('Ошибка при сохранении себестоимости:', err);
        alert(`Ошибка при сохранении себестоимости: ${err.message}`);
      }
    });
  };

  // Загрузка сохраненной себестоимости при получении товаров
  useEffect(() => {
    const savedCosts = localStorage.getItem('productCosts');
    
    if (savedCosts && products.length > 0) {
      try {
        const costsData = JSON.parse(savedCosts) as Array<{product_id: number, offer_id: string, cost: number}>;
        const productsWithCosts = products.map(product => {
          const savedProduct = costsData.find(p => p.product_id === product.product_id);
          return savedProduct ? {...product, cost: savedProduct.cost} : product;
        });
        
        setProducts(productsWithCosts);
      } catch (error) {
        console.error('Ошибка при загрузке себестоимости:', error);
      }
    }
  }, [products.length]);

  return (
    <div className="app">
      {/* Переключатель темы */}
      <div className="theme-toggle" onClick={toggleTheme}>
        {isDarkTheme ? (
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 3a9 9 0 109 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 01-4.4 2.26 5.403 5.403 0 01-3.14-9.8c-.44-.06-.9-.1-1.36-.1z" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 7a5 5 0 100 10 5 5 0 000-10zM12 2a1 1 0 011 1v2a1 1 0 11-2 0V3a1 1 0 011-1zm0 16a1 1 0 011 1v2a1 1 0 11-2 0v-2a1 1 0 011-1zm2 0a1 1 0 011 1v2a1 1 0 11-2 0v-2a1 1 0 011-1zM2 12a1 1 0 011-1h2a1 1 0 110 2H3a1 1 0 01-1-1zm16 0a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1zM4.929 5.343a1 1 0 011.414 0l1.414 1.414a1 1 0 01-1.414 1.414L4.93 6.757a1 1 0 010-1.414zm12.728 12.728a1 1 0 011.414 0l1.414 1.414a1 1 0 01-1.414 1.414l-1.414-1.414a1 1 0 010-1.414zM4.929 18.657a1 1 0 010-1.414l1.414-1.414a1 1 0 111.414 1.414l-1.414 1.414a1 1 0 01-1.414 0zm12.728-12.728a1 1 0 010-1.414l1.414-1.414a1 1 0 111.414 1.414l-1.414 1.414a1 1 0 01-1.414 0z" />
          </svg>
        )}
      </div>
      <div className="content">
        {activeTab === 'home' && (
          <div className="home-container">
            <h1>Ozon Bot - Панель управления</h1>
            <div className="dashboard-summary">
              <div className="summary-card">
                <h3>Товары</h3>
                <p className="summary-value">3</p>
                <p>Активные товары в каталоге</p>
              </div>
              <div className="summary-card">
                <h3>Продажи</h3>
                <p className="summary-value">12 500 ₽</p>
                <p>Общая сумма продаж</p>
              </div>
              <div className="summary-card">
                <h3>Заказы</h3>
                <p className="summary-value">5</p>
                <p>Новые заказы за сегодня</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'products' && (
          <div>
            <h1>Товары</h1>
            <div className="header-actions">
              <PeriodSelector />
              <button className="refresh-button" onClick={refreshData}>
                Обновить данные
              </button>
            </div>
            {loading && <p>Загрузка товаров...</p>}
            {error && <p className="error">{error}</p>}
            {!loading && !error && products.length === 0 && (
              <p>Список товаров пуст</p>
            )}
            {!isAuthenticated && !loading && (
              <p className="warning">
                Для получения данных о товарах необходимо ввести API токен Ozon.{' '}
                <button className="link-button" onClick={() => setActiveTab('settings')}>
                  Перейти к настройкам
                </button>
              </p>
            )}
            <div className="products-list">
              <div className="product product-header">
                <div className="product-image"></div>
                <div className="product-name">Наименование</div>
                <div className="product-id">Артикул</div>
                <div className="product-price">Цена (₽)</div>
                <div className="product-cost">Себестоимость (₽)</div>
                <div className="product-margin">Маржа (%)</div>
              </div>
              {products.map(product => {
                // Расчёт значений
                const cost = product.cost || 0;
                const revenue = product.price;
                const profit = revenue - cost;
                const margin = cost > 0 ? (profit / revenue) * 100 : 0;
                const roi = cost > 0 ? (profit / cost) * 100 : 0;
                
                // Цветовая индикация для маржинальности
                const marginClass = margin < notificationThreshold 
                  ? 'low-margin' 
                  : margin > 30 ? 'high-margin' : '';
                
                return (
                  <div key={product.product_id} className="product">
                    <div className="product-image">
                      <img src={product.images[0]} alt={product.name} width="40" />
                    </div>
                    <div className="product-name">{product.name}</div>
                    <div className="product-id">{product.offer_id}</div>
                    <div className="product-price">{product.price.toFixed(2)} ₽</div>
                    <div className="product-cost">
                      <input 
                        type="number" 
                        value={product.cost || ''} 
                        placeholder="Себестоимость" 
                        onChange={(e) => {
                          const newProducts = products.map(p => 
                            p.product_id === product.product_id 
                              ? {...p, cost: parseFloat(e.target.value) || 0} 
                              : p
                          );
                          setProducts(newProducts);
                        }}
                      />
                    </div>
                    <div className={`product-margin ${marginClass}`}>
                      {margin.toFixed(2)}%
                    </div>
                  </div>
                );
              })}
            </div>
            
            {products.length > 0 && (
              <div className="save-costs-container">
                <button className="save-button" onClick={saveCosts}>
                  Сохранить себестоимость
                </button>
                <p className="save-note">
                  * После ввода себестоимости для товаров, нажмите кнопку "Сохранить себестоимость"
                </p>
              </div>
            )}
          </div>
        )}
        {activeTab === 'analytics' && (
          <div>
            <h1>Аналитика</h1>
            <div className="header-actions">
              <PeriodSelector />
              <button className="refresh-button" onClick={refreshData}>
                Обновить данные
              </button>
            </div>
            
            {loading && <p>Загрузка данных...</p>}
            {error && <p className="error">{error}</p>}
            
            {!isAuthenticated && !loading && (
              <p className="warning">
                Для получения аналитики необходимо ввести API токен Ozon.{' '}
                <button className="link-button" onClick={() => setActiveTab('settings')}>
                  Перейти к настройкам
                </button>
              </p>
            )}
            
            {isAuthenticated && !loading && !error && (
              <div className="analytics-container">
                <div className="analytics-row">
                  <div className="analytics-card">
                    <h3>Продажи за период</h3>
                    <p className="analytics-value">{analyticsData.sales.toFixed(2)} ₽</p>
                    <div className="chart-placeholder">
                      {/* Здесь будет график продаж */}
                      <SalesChart data={analyticsData.sales_data} />
                    </div>
                  </div>
                  
                  <div className="analytics-card">
                    <h3>Маржинальность</h3>
                    <p className="analytics-value">{analyticsData.margin.toFixed(2)}%</p>
                    <div className="chart-placeholder">
                      {/* Здесь будет график маржинальности */}
                      <MarginChart data={analyticsData.margin_data} />
                    </div>
                  </div>
                </div>
                
                <div className="analytics-row">
                  <div className="analytics-card">
                    <h3>Средний ROI</h3>
                    <p className="analytics-value">{analyticsData.roi.toFixed(2)}%</p>
                    <div className="chart-placeholder">
                      {/* Здесь будет график ROI */}
                      <ROIChart data={analyticsData.roi_data} />
                    </div>
                  </div>
                  
                  <div className="analytics-card">
                    <h3>Общая прибыль</h3>
                    <p className="analytics-value">{analyticsData.profit.toFixed(2)} ₽</p>
                    <div className="chart-placeholder">
                      {/* Здесь будет график прибыли */}
                      <div className="chart-mockup">
                        <div className="bar" style={{ height: `${analyticsData.profit / analyticsData.sales * 100}%` }}></div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="analytics-summary">
                  <h3>Сводка по магазину</h3>
                  <div className="summary-metrics">
                    <div className="metric">
                      <span className="metric-label">Общее количество товаров:</span>
                      <span className="metric-value">{analyticsData.total_products}</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Активные товары:</span>
                      <span className="metric-value">{analyticsData.active_products}</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Средняя прибыль с товара:</span>
                      <span className="metric-value">
                        {analyticsData.total_products > 0 
                          ? (analyticsData.profit / analyticsData.total_products).toFixed(2) 
                          : '0.00'} ₽
                      </span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Низкомаржинальные товары:</span>
                      <span className="metric-value">
                        {products.filter(p => {
                          const cost = p.cost || 0;
                          const revenue = p.price;
                          const profit = revenue - cost;
                          const margin = cost > 0 ? (profit / revenue) * 100 : 0;
                          return margin < notificationThreshold;
                        }).length}
                      </span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Средний ROI:</span>
                      <span className="metric-value">{analyticsData.roi.toFixed(2)}%</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Заказы за период:</span>
                      <span className="metric-value">{analyticsData.orders}</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Средний чек:</span>
                      <span className="metric-value">{analyticsData.average_order.toFixed(2)} ₽</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Комиссии маркетплейса:</span>
                      <span className="metric-value">{analyticsData.marketplace_fees.toFixed(2)} ₽</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">Затраты на рекламу:</span>
                      <span className="metric-value">{analyticsData.advertising_costs.toFixed(2)} ₽</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            <button className="report-button" onClick={sendReport}>
              Отправить отчет в Telegram
            </button>
            {reportStatus && (
              <p className={reportStatus.includes('Ошибка') ? 'error' : 'success'}>
                {reportStatus}
              </p>
            )}
          </div>
        )}
        {activeTab === 'settings' && (
          <div className="settings-container">
            <h1>Настройки</h1>
            <div className="settings-form">
              <div className="telegram-auth-container">
                <div className="telegram-auth-info">
                  <h2>Авторизация через Telegram</h2>
                  <p>
                    Для работы с API Ozon необходимо получить токены через Telegram бота. 
                    Пожалуйста, используйте бота <a href="https://t.me/xyezonbot/shmazon" target="_blank" rel="noopener noreferrer">@xyezonbot</a> для настройки токенов.
                  </p>
                  <div className="telegram-instructions">
                    <h3>Как настроить токены:</h3>
                    <ol>
                      <li>Откройте бота <a href="https://t.me/xyezonbot/shmazon" target="_blank" rel="noopener noreferrer">@xyezonbot</a></li>
                      <li>Отправьте команду /set_token</li>
                      <li>Следуйте инструкциям бота для ввода API токена и Client ID Ozon</li>
                      <li>После успешной настройки токенов, обновите эту страницу</li>
                    </ol>
                  </div>
                </div>
                
                {telegramUser ? (
                  <div className="telegram-status">
                    <h3>Статус подключения</h3>
                    <p className="telegram-user-info">
                      Вы авторизованы как: <strong>{telegramUser.username || `Пользователь ${telegramUser.id}`}</strong>
                    </p>
                    <p>
                      {isAuthenticated ? 
                        "✅ API токены настроены и готовы к использованию" : 
                        "❌ API токены не настроены. Пожалуйста, используйте бота для настройки токенов"}
                    </p>
                    {isAuthenticated && (
                      <div className="token-info">
                        <p>Client ID: <code>{apiTokens.ozon_client_id}</code></p>
                        <p>API Token: <code>{apiTokens.ozon_api_token.substring(0, 5)}...{apiTokens.ozon_api_token.substring(apiTokens.ozon_api_token.length - 5)}</code></p>
                      </div>
                    )}
                    <button type="button" className="refresh-button" onClick={() => fetchUserTokensFromBot(telegramUser.id)}>
                      Обновить токены
                    </button>
                  </div>
                ) : (
                  <div className="telegram-login">
                    <p>Для использования приложения, пожалуйста, введите ваш Telegram ID:</p>
                    <form onSubmit={(e) => {
                      e.preventDefault();
                      const input = e.currentTarget.querySelector('input[type="number"]') as HTMLInputElement;
                      const telegramId = parseInt(input.value);
                      setTelegramUser({id: telegramId});
                      fetchUserTokensFromBot(telegramId);
                    }}>
                      <input type="number" placeholder="Введите Telegram ID" required />
                      <button type="submit" className="report-button">Авторизоваться</button>
                    </form>
                    <p className="hint">Вы можете узнать свой Telegram ID, отправив команду /status боту @xyezonbot</p>
                  </div>
                )}
              </div>
              
              <div className="other-settings">
                <h3>Настройки приложения</h3>
                <div className="form-group">
                  <label>Порог маржинальности для уведомлений (%)</label>
                  <input 
                    type="number" 
                    min="0" 
                    max="100" 
                    placeholder="Введите порог в %" 
                    value={notificationThreshold} 
                    onChange={(e) => setNotificationThreshold(Number(e.target.value))}
                  />
                </div>
                <div className="form-group">
                  <label>Тема приложения</label>
                  <button 
                    type="button" 
                    className="theme-button" 
                    onClick={toggleTheme}
                  >
                    {isDarkTheme ? 'Переключить на светлую тему' : 'Переключить на темную тему'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="navbar">
        <button 
          onClick={() => setActiveTab('home')}
          className={activeTab === 'home' ? 'active' : ''}
        >
          Главная
        </button>
        <button 
          onClick={() => setActiveTab('products')}
          className={activeTab === 'products' ? 'active' : ''}
        >
          Товары
        </button>
        <button 
          onClick={() => setActiveTab('analytics')}
          className={activeTab === 'analytics' ? 'active' : ''}
        >
          Аналитика
        </button>
        <button 
          onClick={() => setActiveTab('settings')}
          className={activeTab === 'settings' ? 'active' : ''}
        >
          Настройка
        </button>
      </div>
    </div>
  );
}

export default App;