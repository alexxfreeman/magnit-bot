FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости (без playwright!)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]
