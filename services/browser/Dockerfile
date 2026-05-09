FROM python:3.12-slim

WORKDIR /app

# Зависимости сервиса — отдельный кешируемый слой.
COPY services/browser/pyproject.toml .
RUN pip install --no-cache-dir -e .

# Установка браузера зависит от архитектуры:
#
# AMD64 (облако, x86_64): Google Chrome Stable + все системные зависимости.
# Qrator пропускает Chrome TLS fingerprint — именно это работает на avito.ru.
# BROWSER_BACKEND=playwright + BROWSER_CHANNEL=chrome в этом режиме.
#
# ARM64 (Mac Apple Silicon, локальная разработка): Google Chrome недоступен
# для Linux ARM64. Устанавливаем Camoufox — Firefox с C++-level anti-detect.
# Для avito.ru на ARM64 используй нативный Mac Chrome (вне Docker) с
# BROWSER_SERVICE_URL=http://host.docker.internal:8003.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      echo "AMD64: устанавливаем Google Chrome + системные зависимости" && \
      apt-get update && apt-get install -y xvfb && rm -rf /var/lib/apt/lists/* && \
      playwright install --with-deps chrome; \
    else \
      echo "ARM64: устанавливаем Camoufox (Firefox anti-detect)" && \
      apt-get update && apt-get install -y \
        xvfb xserver-common libgtk-3-0 libx11-xcb1 libdbus-glib-1-2 libasound2 \
        fonts-dejavu fonts-liberation && \
      rm -rf /var/lib/apt/lists/* && \
      for i in 1 2 3; do python -m camoufox fetch && break || sleep 5; done; \
    fi

COPY services/browser/browser/ browser/

EXPOSE 8003

CMD ["uvicorn", "browser.api:app", "--host", "0.0.0.0", "--port", "8003"]
