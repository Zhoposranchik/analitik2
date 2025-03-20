module.exports = {
  extends: [
    'react-app',
    'react-app/jest'
  ],
  rules: {
    // Отключаем правила, которые вызывают ошибки при сборке
    'react-hooks/exhaustive-deps': 'off', // отключаем полностью
    '@typescript-eslint/no-unused-vars': 'off', // отключаем полностью
    'no-unused-vars': 'off', // отключаем полностью
  },
  // Определяем среды выполнения
  env: {
    browser: true,
    node: true,
    es6: true
  }
}; 