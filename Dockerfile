FROM python:3.12-slim

WORKDIR /app

# Зависимости отдельным слоем — пересборка только при изменении pyproject.toml.
# Паттерн «layer caching»: сначала ставим тяжёлое (deps), потом копируем код.
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY catalog/ catalog/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8002

CMD ["uvicorn", "catalog.api:app", "--host", "0.0.0.0", "--port", "8002"]
