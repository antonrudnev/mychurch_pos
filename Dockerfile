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

# Сборка статических файлов (включая стили админки) внутрь контейнера
RUN python manage.py collectstatic --noinput

# Открываем порт для Django
EXPOSE 8000

# Запуск через WSGI-сервер Gunicorn (замените "myproject" на имя папки с вашим settings.py)
CMD ["gunicorn", "--workers", "5", "--bind", "0.0.0.0:8000", "config.wsgi:application"]