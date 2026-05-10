# =============================================================================
# Stage 1: сборка React-фронтенда
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Устанавливаем зависимости отдельным слоем (кэшируется при изменении только кода)
COPY services/web-test/frontend/package*.json ./
RUN npm ci --silent

# Копируем исходники и собираем
COPY services/web-test/frontend/ ./
RUN npm run build


# =============================================================================
# Stage 2: Python-бэкенд + собранный фронтенд
# =============================================================================
FROM python:3.12-slim-bookworm

WORKDIR /app

# postgresql-client-16 нужен для pg_dump в /api/catalog/backup. Подключаемся
# к контейнеру postgres напрямую по docker-сети `bg` — без docker socket
# и без docker CLI.
#
# Версия клиента ДОЛЖНА совпадать с major-версией сервера (postgres:16-alpine
# в docker-compose.yml). В debian bookworm дефолтный `postgresql-client`
# равен 15 или 17, и pg_dump>=17 пишет формат `1.16`, который pg_restore 16
# не читает («unsupported version in file header»). Поэтому ставим клиент
# из официального PGDG-репозитория с pin'ом на 16.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# Все Python-зависимости имеют pre-built wheels (pydantic, fastapi, uvicorn,
# aiosqlite, httpx, python-dotenv) — компилятор не нужен.

# Сначала устанавливаем shared-пакет, от которого зависит parsers.
# Build context = корень монорепо (см. docker-compose.yml: web-test.build.context: .)
COPY packages/shared-py/ /tmp/shared-py/
RUN pip install --no-cache-dir /tmp/shared-py/ && rm -rf /tmp/shared-py/

# Устанавливаем parsers как пакет (не editable — для production-образа).
COPY services/parsers/ /tmp/parsers/
RUN pip install --no-cache-dir /tmp/parsers/ && rm -rf /tmp/parsers/

# Устанавливаем дополнительные зависимости parsers_web_test
# (fastapi, uvicorn, aiosqlite уже пришли через parsers).
# python-multipart нужен FastAPI для UploadFile/Form (catalog import-CSV proxy).
RUN pip install --no-cache-dir \
    "pydantic>=2" \
    "python-dotenv>=1.0" \
    "python-multipart>=0.0.9"

# Копируем исходный код приложения
COPY services/web-test/app/ ./app/

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
