FROM python:3.12-slim-bookworm

WORKDIR /app

# Зависимости сервиса отдельным слоем — пересборка только при изменении pyproject.toml.
COPY services/browser/pyproject.toml .
RUN pip install --no-cache-dir -e .

# Установка Chromium + все системные зависимости (~400 MB, тяжёлый кешируемый слой).
# --with-deps автоматически ставит нужные apt-пакеты (libnss3, libatk и др.).
RUN playwright install --with-deps chromium

COPY services/browser/browser/ browser/

EXPOSE 8003

CMD ["uvicorn", "browser.api:app", "--host", "0.0.0.0", "--port", "8003"]
