FROM python:3.12-slim

WORKDIR /app

# Зависимости сервиса — отдельный кешируемый слой.
COPY services/browser/pyproject.toml .
RUN pip install --no-cache-dir -e .

# На AMD64 (облако, x86_64) устанавливаем реальный Google Chrome —
# у него другой TLS-отпечаток и headless-режим, которые Qrator воспринимает
# как доверенный браузер. На ARM64 (Mac Apple Silicon) Chrome недоступен
# для Linux — используем Chromium.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      echo "AMD64: устанавливаем Google Chrome" && \
      playwright install --with-deps chrome; \
    else \
      echo "ARM64: Google Chrome недоступен, устанавливаем Chromium" && \
      playwright install --with-deps chromium; \
    fi

COPY services/browser/browser/ browser/

EXPOSE 8003

CMD ["uvicorn", "browser.api:app", "--host", "0.0.0.0", "--port", "8003"]
