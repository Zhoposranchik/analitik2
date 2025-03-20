/// <reference types="react-scripts" />

interface TelegramWebAppUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
}

interface TelegramWebAppInitData {
  query_id?: string;
  user?: TelegramWebAppUser;
  start_param?: string;
  auth_date?: number;
  hash?: string;
}

interface TelegramWebAppBackButton {
  isVisible: boolean;
  onClick(callback: () => void): void;
  offClick(callback: () => void): void;
  show(): void;
  hide(): void;
}

interface TelegramWebAppMainButton {
  text: string;
  color: string;
  textColor: string;
  isVisible: boolean;
  isActive: boolean;
  isProgressVisible: boolean;
  setText(text: string): void;
  onClick(callback: () => void): void;
  offClick(callback: () => void): void;
  show(): void;
  hide(): void;
  enable(): void;
  disable(): void;
  showProgress(leaveActive?: boolean): void;
  hideProgress(): void;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: TelegramWebAppInitData;
  colorScheme: 'light' | 'dark';
  viewportHeight: number;
  viewportStableHeight: number;
  headerColor: string;
  backgroundColor: string;
  isExpanded: boolean;
  ready(): void;
  expand(): void;
  close(): void;
  onEvent(eventType: string, callback: () => void): void;
  offEvent(eventType: string, callback: () => void): void;
  sendData(data: any): void;
  openLink(url: string): void;
  openTelegramLink(url: string): void;
  BackButton: TelegramWebAppBackButton;
  MainButton: TelegramWebAppMainButton;
  showAlert(message: string): void;
  showConfirm(message: string, callback: (ok: boolean) => void): void;
  showPopup(params: {
    title?: string;
    message: string;
    buttons?: Array<{
      id?: string;
      type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive';
      text?: string;
    }>;
  }, callback?: (buttonId: string) => void): void;
}

interface Window {
  Telegram?: {
    WebApp: TelegramWebApp;
  };
}

interface ApiTokens {
  ozon_api_token: string;
  ozon_client_id: string;
  telegram_bot_token?: string;
  telegram_chat_id?: string;
}

interface Product {
  product_id: number;
  name: string;
  offer_id: string;
  price: number;
  images: string[];
  cost?: number;
}
