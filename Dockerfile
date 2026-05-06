FROM python:3.12-slim

WORKDIR /app

# Зависимости отдельным слоем — пересборка только при изменении pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY parsers/ parsers/

# Директория для SQLite-файла
RUN mkdir -p data

ENV DB_PATH=data/prices.sqlite
ENV CACHE_TTL_HOURS=4

EXPOSE 8000

CMD ["uvicorn", "parsers.api:app", "--host", "0.0.0.0", "--port", "8000"]
