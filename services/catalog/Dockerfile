FROM python:3.12-slim

WORKDIR /app

# bg-shared — workspace-пакет из packages/shared-py.
# Устанавливаем первым отдельным слоем: меняется реже сервисного кода.
COPY packages/shared-py/ packages/shared-py/
RUN pip install --no-cache-dir packages/shared-py/

# Зависимости сервиса отдельным слоем — пересборка только при изменении pyproject.toml.
# Паттерн «layer caching»: сначала ставим тяжёлое (deps), потом копируем код.
COPY services/catalog/pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY services/catalog/catalog/ catalog/
COPY services/catalog/alembic/ alembic/
COPY services/catalog/alembic.ini .

EXPOSE 8002

CMD ["uvicorn", "catalog.api:app", "--host", "0.0.0.0", "--port", "8002"]
