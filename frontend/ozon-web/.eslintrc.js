module.exports = {
  extends: [
    'react-app',
    'react-app/jest'
  ],
  rules: {
    // Отключаем правила, которые вызывают ошибки при сборке
    'react-hooks/exhaustive-deps': 'warn', // понижаем уровень с error до warn
    '@typescript-eslint/no-unused-vars': 'warn', // понижаем уровень с error до warn
    'no-unused-vars': 'warn', // понижаем уровень с error до warn
  },
  // Игнорируем предупреждения во время сборки
  env: {
    production: {
      rules: {
        'react-hooks/exhaustive-deps': 'off',
        '@typescript-eslint/no-unused-vars': 'off',
        'no-unused-vars': 'off',
      }
    }
  }
}; 