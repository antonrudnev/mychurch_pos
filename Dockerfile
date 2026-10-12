FROM python:3.14-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Настройка переменных окружения Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Обновление pip и установка зависимостей
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода проекта
COPY . .

# Открываем порт для Django
EXPOSE 8000

# Команда для запуска встроенного сервера (для продакшна обычно используют gunicorn)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]