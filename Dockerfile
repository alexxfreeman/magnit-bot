FROM python:3.12-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем Python-пакеты
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Скачиваем Chromium И системные зависимости одной командой
RUN python -m playwright install --with-deps chromium

# Копируем код
COPY . .

# Запуск
CMD ["python", "bot.py"]
