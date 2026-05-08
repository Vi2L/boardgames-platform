FROM python:3.12-slim

WORKDIR /app

# bg-shared — workspace-пакет из packages/shared-py.
# Устанавливаем первым отдельным слоем: меняется реже сервисного кода.
COPY packages/shared-py/ packages/shared-py/
RUN pip install --no-cache-dir packages/shared-py/

# Зависимости сервиса отдельным слоем — пересборка только при изменении pyproject.toml
COPY services/parsers/pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY services/parsers/parsers/ parsers/

# Директория для SQLite-файла
RUN mkdir -p data

ENV DB_PATH=data/prices.sqlite
ENV CACHE_TTL_HOURS=4

EXPOSE 8001

CMD ["uvicorn", "parsers.api:app", "--host", "0.0.0.0", "--port", "8001"]
