# apps/

Заготовка под пользовательские приложения. Сейчас пусто.

В будущем сюда приедут:

- **`apps/web/`** — пользовательский веб-портал. Возможные стеки: Next.js или Vite + React + SSR.
  Использует API из `services/catalog/` (поиск игр, ведение коллекции, поиск лучших цен).

- **`apps/mobile/`** — мобильное приложение для записи партий и ведения коллекции.
  React Native + Expo либо нативные iOS/Android.

Оба используют общий TypeScript-клиент из `packages/shared-ts/` (генерируется из FastAPI `/openapi.json`).

## Чем `apps/` отличается от `services/`

| | services/ | apps/ |
|---|---|---|
| Что | бэкенд-процесс (FastAPI и т.п.) | конечное приложение для пользователя (web, mobile) |
| Стек | Python | TypeScript / JavaScript |
| Member uv workspace | да | нет (это JS, не Python) |
| Сборка | `uv sync` + `uvicorn` | `npm install` + `vite build` / `expo` |
