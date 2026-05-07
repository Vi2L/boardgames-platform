# packages/

Заготовка под переиспользуемые библиотеки. Сейчас пусто.

В будущем сюда приедут:

- **`packages/shared-py/`** — общие pydantic-схемы для inter-service контрактов.
  Сейчас `IngestRequest` дублируется в `services/parsers/parsers/catalog_publisher.py`
  (как dict) и в `services/catalog/catalog/schemas.py` (как Pydantic) — извлечение
  устранит рассинхрон. Будет членом uv workspace.

- **`packages/shared-ts/`** — TypeScript-клиент catalog API.
  Генерируется из `/openapi.json` каталога, потребляется в `apps/web/` и `apps/mobile/`.
  Не member uv workspace (это TypeScript, не Python).

## Когда выносить код в `packages/`

Не сразу. Правило **«trois fois et tu réutilises»** (три раза и переиспользуй):
если модель/функция дублируется минимум в двух местах и контракт стабилен —
извлекаем в `packages/`. До этого — преждевременная абстракция.
