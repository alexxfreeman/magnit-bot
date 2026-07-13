FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем браузер для Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Копируем код
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]
