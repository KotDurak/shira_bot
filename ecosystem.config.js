module.exports = {
  apps: [
    {
      name: 'shira-bot',
      script: 'main.py',

      // ⚠️ ВАЖНО: Укажи здесь реальный путь к python.exe из твоего виртуального окружения
      // Пример: 'C:\\python\\shira_bot\\venv\\Scripts\\python.exe'
      // Не забудь использовать двойные обратные слеши (\\) для Windows!
      interpreter: 'C:\\projects\\shira_bot\\venv\\Scripts\\python.exe',

      // ⚠️ ВАЖНО: Укажи здесь реальную папку с проектом (где лежит main.py и shira_bot.db)
      cwd: 'C:\\projects\\shira_bot',

      // === СТРАТЕГИИ РЕАНИМАЦИИ ===
      autorestart: true,
      exp_backoff_restart_delay: 100, // Защита от WinError 64 и кратковременных обрывов сети
      max_restarts: 10,               // Лимит перезапусков, чтобы не уйти в бесконечный цикл
      min_uptime: '5s',               // Если бот живет меньше 5 секунд — считаем это крашем
      max_memory_restart: '500M',     // Защита от утечек памяти (для Python более чем достаточно)
      restart_delay: 4000,            // Пауза между обычными рестартами

      // Логи в папку проекта (удобнее искать ошибки)
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',

      // Переменные окружения
      env: {
        PYTHONUNBUFFERED: '1'  // Чтобы логи не буферизировались и были видны в pm2 logs сразу
      }
    }
  ]
};