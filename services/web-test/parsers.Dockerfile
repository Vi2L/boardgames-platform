# Образ для parsers-сервиса (FastAPI на порту 8001)
# Контекст сборки: родительская папка (../), содержащая parsers/
FROM python:3.12-slim

WORKDIR /app

# setuptools нужен для сборки пакета с [build-system] = setuptools
RUN pip install --no-cache-dir setuptools>=68

COPY parsers/ .

RUN pip install --no-cache-dir -e .

RUN mkdir -p data

ENV DB_PATH=data/prices.sqlite
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/stores')" || exit 1

CMD ["uvicorn", "parsers.api:app", "--host", "0.0.0.0", "--port", "8001"]
