# =============================================================================
# Stage 1: сборка React-фронтенда
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Устанавливаем зависимости отдельным слоем (кэшируется при изменении только кода)
COPY parsers_web_test/frontend/package*.json ./
RUN npm ci --silent

# Копируем исходники и собираем
COPY parsers_web_test/frontend/ ./
RUN npm run build


# =============================================================================
# Stage 2: Python-бэкенд + собранный фронтенд
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# Все Python-зависимости имеют pre-built wheels (pydantic, fastapi, uvicorn,
# aiosqlite, httpx, python-dotenv) — компилятор не нужен.

# Устанавливаем parsers как пакет (не editable — для production-образа)
COPY parsers/ /tmp/parsers/
RUN pip install --no-cache-dir /tmp/parsers/ && rm -rf /tmp/parsers/

# Устанавливаем дополнительные зависимости parsers_web_test
# (fastapi, uvicorn, aiosqlite уже пришли через parsers)
RUN pip install --no-cache-dir \
    "pydantic>=2" \
    "python-dotenv>=1.0"

# Копируем исходный код приложения
COPY parsers_web_test/app/ ./app/

# Копируем собранный фронтенд — FastAPI отдаёт его как статику
COPY --from=frontend-builder /build/dist ./frontend/dist/

# Директория для SQLite-файла (монтируется как volume)
RUN mkdir -p data

# Переменные окружения по умолчанию
ENV DB_PATH=data/debug.sqlite
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/stores')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
