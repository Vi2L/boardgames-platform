# API Reference — Board Game Price Parser

Сервис сравнения цен на настольные игры. Парсит 3 российских интернет-магазина (Лавка Игр, GaGa.ru, HobbyGames), кеширует результаты в SQLite и отдаёт единый JSON API.

## Запуск и базовый URL

```bash
# Установка (в папке parsers/)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Запуск сервера
.venv/bin/uvicorn parsers.api:app --reload --port 8001
```

```
Base URL: http://127.0.0.1:8001
```

**Важно для web-приложения:** сервер не настроен на CORS по умолчанию. Перед разработкой добавьте в `parsers/api.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # или конкретный origin фронтенда
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

Все ответы — `application/json`, кодировка UTF-8.

---

## Эндпоинты

### `GET /stores` — список магазинов

Возвращает список подключённых магазинов.

**Параметры:** нет

**Ответ** `200 OK`:

```json
[
  { "slug": "hobbygames", "name": "HobbyGames",  "base_url": "https://hobbygames.ru"      },
  { "slug": "lavkaigr",   "name": "Лавка Игр",   "base_url": "https://www.lavkaigr.ru"   },
  { "slug": "gaga",       "name": "GaGa.ru",      "base_url": "https://gaga.ru"           }
]
```

| Поле | Тип | Описание |
|------|-----|----------|
| `slug` | string | Идентификатор магазина для фильтрации |
| `name` | string | Человекочитаемое название |
| `base_url` | string | Базовый URL магазина |

---

### `GET /search` — поиск игры

Поиск по названию игры. Возвращает цены из кеша (если свежие) или запускает парсинг.

**Параметры запроса:**

| Параметр | Тип | Обязательный | По умолчанию | Описание |
|----------|-----|:------------:|:------------:|----------|
| `q` | string | ✅ | — | Название игры (мин. 1 символ) |
| `refresh` | boolean | — | `false` | Принудительно обновить кеш (игнорирует TTL) |
| `stores` | string | — | все | Фильтр магазинов через запятую: `lavkaigr,gaga` |
| `limit` | integer | — | `10` | Кол-во результатов (1–50) |

**Пример запросов:**

```bash
# Поиск по всем магазинам
curl "http://127.0.0.1:8001/search?q=Каркассон"

# Только Лавка Игр, 5 результатов
curl "http://127.0.0.1:8001/search?q=Каркассон&stores=lavkaigr&limit=5"

# Принудительное обновление
curl "http://127.0.0.1:8001/search?q=Каркассон&refresh=true"
```

```javascript
// JavaScript / fetch
const res = await fetch(`http://127.0.0.1:8001/search?q=${encodeURIComponent('Каркассон')}&limit=10`);
const data = await res.json();
```

**Ответ** `200 OK`:

```json
{
  "source": "network",
  "errors": {},
  "products": [ /* массив Product Object — см. ниже */ ]
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `source` | string | Источник данных (см. [Кеш](#поведение-кеша)) |
| `errors` | object | Ошибки по магазинам `{ "slug": "описание" }`. Пустой объект если всё ок |
| `products` | array | Массив [Product Object](#product-object) |

**Ответ** `503 Service Unavailable` — все магазины недоступны **и** кеш пустой:

```json
{ "detail": "Все магазины вернули ошибку и кеша нет. Ошибки: {...}" }
```

---

### `GET /history/{product_id}` — история цен

Возвращает все зафиксированные цены на конкретный товар в хронологическом порядке.

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `product_id` | integer | `id` товара из ответа `/search` |

**Ответ** `200 OK`:

```json
[
  { "price": 199000, "fetched_at": "2026-05-06T18:47:58.722698+00:00" },
  { "price": 185000, "fetched_at": "2026-04-10T12:00:00.000000+00:00" }
]
```

> ⚠️ **Важно:** `price` здесь в **копейках**, не в рублях (в отличие от `/search`).  
> Для перевода: `price_rub = price / 100`

| Поле | Тип | Описание |
|------|-----|----------|
| `price` | integer | Цена **в копейках** |
| `fetched_at` | string | Время получения цены (ISO-8601 UTC) |

**Ответ** `404 Not Found` — товар не найден:

```json
{ "detail": "Товар не найден или истории нет" }
```

---

## Product Object

Полная схема одного товара в ответе `/search`.

```json
{
  "id": 1,
  "store_slug": "lavkaigr",
  "title": "Каркассон (2019)",
  "price_rub": 1990.0,
  "url": "https://www.lavkaigr.ru/shop/family/karkasson-2019/",
  "image_url": "https://media.lavkaigr.ru/cache/63/d1/63d1940c2a20241e0845b845c718e18a.png",
  "image_url_hd": "https://media.lavkaigr.ru/catalog/2022/09/karkasson-2019.jpg",
  "description": "Вы - феодальный правитель одной из провинций средневековой Франции...",
  "players": "2-5",
  "age_min": 8,
  "playtime": "30-45 мин.",
  "rules_url": "https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf",
  "fetched_at": "2026-05-06T18:47:58.722698+00:00",
  "extra": {
    "category": "family",
    "tags": ["выкладывание плиток", "управление областями"],
    "language": "Русский",
    "complexity": "3 мин",
    "gallery": [
      "https://media.lavkaigr.ru/cache/63/d1/63d1940c2a20241e0845b845c718e18a.png",
      "https://media.lavkaigr.ru/cache/65/f5/65f58aceb28a79f70e29539904266a57.png"
    ],
    "rules": [
      { "url": "https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf", "name": "Правила" },
      { "url": "https://media.lavkaigr.ru/uploads/Karkasson_solo_web.pdf",   "name": "Соло-режим" }
    ],
    "composition": [
      "72 квадрата участков земли;",
      "40 фишек 5-ти цветов;",
      "Поле шкалы подсчёта очков;",
      "Правила игры."
    ]
  }
}
```

### Основные поля

| Поле | Тип | Nullable | Описание |
|------|-----|:--------:|----------|
| `id` | integer | — | Внутренний ID в БД. Используется для запроса истории цен |
| `store_slug` | string | — | Магазин: `"hobbygames"` / `"lavkaigr"` / `"gaga"` |
| `title` | string | — | Название игры |
| `price_rub` | number | — | Цена в **рублях** (float) |
| `url` | string | — | Ссылка на страницу товара |
| `image_url` | string | ✅ | Thumbnail (~200px) со страницы поиска |
| `image_url_hd` | string | ✅ | HD-изображение со страницы товара |
| `description` | string | ✅ | Описание игры |
| `players` | string | ✅ | Кол-во игроков, e.g. `"2-5"` или `"2-6"` |
| `age_min` | integer | ✅ | Минимальный возраст в годах, e.g. `8` |
| `playtime` | string | ✅ | Время партии, e.g. `"30-45 мин."` или `"0.5 - 1.5 ч."` |
| `rules_url` | string | ✅ | Ссылка на основной PDF правил |
| `fetched_at` | string | — | Время последнего обновления цены (ISO-8601 UTC) |
| `extra` | object | — | Дополнительные поля (см. ниже). Всегда объект, может быть пустым `{}` |

> **Nullable (✅):** поле может быть `null` если сайт не предоставил данные. У HobbyGames отсутствуют `players`, `age_min`, `playtime` — эти поля будут `null`.

### Поле `extra` — дополнительные данные

Содержимое `extra` зависит от магазина. Все ключи опциональны — проверяйте наличие перед использованием.

| Ключ | Тип | Магазины | Описание |
|------|-----|----------|----------|
| `gallery` | string[] | все | Список URL изображений. Лавка — thumbnail-кеш (~19 шт.), GaGa — fullsize (~8 шт.), HobbyGames — все размеры одного фото + обложки дополнений (~38 URL) |
| `availability` | boolean | hobbygames | `true` — товар в наличии |
| `sku` | string | hobbygames | Артикул, e.g. `"UT-00018963"` |
| `tags` | string[] | lavkaigr | Игровые механики, e.g. `["выкладывание плиток"]` |
| `category` | string | hobbygames, lavkaigr | HobbyGames: `"Семейные игры"`. Лавка: slug из URL `"family"` |
| `language` | string | lavkaigr | Язык игры, e.g. `"Русский"` |
| `complexity` | string | lavkaigr, gaga | GaGa: `"правила простые"`. Лавка: время освоения `"3 мин"` |
| `rules` | array | все | Все PDF правил. Лавка: `[{"url": "...", "name": "..."}]`. GaGa и HobbyGames: `["url1", "url2"]` |
| `composition` | string[] / string | lavkaigr, gaga | Состав игры. Лавка: массив строк. GaGa: одна строка с `•` как разделителем |
| `rating` | string | gaga | Рейтинг из 5, e.g. `"4.8"` |
| `review_count` | string | gaga | Количество отзывов, e.g. `"12"` |
| `ranking` | string | gaga | Место в рейтинге сайта, e.g. `"2 место"` |
| `offline_price` | integer | gaga | Цена без регистрации в **копейках**, e.g. `234000` (2340 руб.) |
| `dimensions` | string | gaga | Размеры коробки, e.g. `"27.7см x 19.4см x 6.7см"` |
| `weight` | string | gaga | Вес, e.g. `"900 гр."` |

---

## Магазины

| `slug` | Название | Доступность | Примечания |
|--------|----------|-------------|------------|
| `lavkaigr` | Лавка Игр | Без ограничений | Доступен с любого IP |
| `gaga` | GaGa.ru | Без ограничений | Доступен с любого IP |
| `hobbygames` | HobbyGames | Без ограничений | Работает с любого IP |

---

## Поведение кеша

Поле `source` в ответе `/search` показывает источник данных:

| Значение | Описание |
|----------|----------|
| `"cache"` | Все магазины свежие (данные моложе 4 часов). Сеть не использовалась |
| `"network"` | Хотя бы один магазин был обновлён по сети |
| `"partial-cache"` | Все магазины вернули ошибку, но в кеше есть устаревшие данные |

**TTL кеша** — 4 часа по умолчанию. Управляется переменной `CACHE_TTL_HOURS`.

Параметр `refresh=true` игнорирует TTL и всегда обращается к магазинам напрямую.

---

## Обработка ошибок

### Частичные ошибки (200 с `errors`)

Если один или несколько магазинов недоступны, но хотя бы один ответил:

```json
{
  "source": "network",
  "errors": {
    "hobbygames": "Connection timeout after 20 seconds"
  },
  "products": [ /* результаты из доступных магазинов */ ]
}
```

### Полный отказ (503)

Все магазины недоступны **и** кеш пустой (первый запрос после очистки БД):

```json
{ "detail": "Все магазины вернули ошибку и кеша нет. Ошибки: {...}" }
```

### HTTP коды

| Код | Ситуация |
|-----|----------|
| `200` | Успех |
| `404` | История цен для товара не найдена (`GET /history/{id}`) |
| `422` | Неверные параметры запроса (FastAPI валидация) |
| `503` | Все магазины недоступны и кеш пустой |

---

## Полные примеры ответов

### `/search?q=Каркассон&stores=lavkaigr&limit=1`

```json
{
  "source": "network",
  "errors": {},
  "products": [
    {
      "id": 1,
      "store_slug": "lavkaigr",
      "title": "Каркассон (2019)",
      "price_rub": 1990.0,
      "url": "https://www.lavkaigr.ru/shop/family/karkasson-2019/",
      "image_url": "https://media.lavkaigr.ru/cache/63/d1/63d1940c2a20241e0845b845c718e18a.png",
      "image_url_hd": "https://media.lavkaigr.ru/catalog/2022/09/karkasson-2019.jpg",
      "description": "Вы - феодальный правитель одной из провинций средневековой Франции. Вам предстоит расширять свои владения, строить города и монастыри, прокладывать дороги ...",
      "players": "2-5",
      "age_min": 8,
      "playtime": "30-45 мин.",
      "rules_url": "https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf",
      "fetched_at": "2026-05-06T19:36:12.232581+00:00",
      "extra": {
        "category": "family",
        "complexity": "3 мин",
        "language": "Русский",
        "tags": ["выкладывание плиток", "управление областями"],
        "rules": [
          { "url": "https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf", "name": "Правила" },
          { "url": "https://media.lavkaigr.ru/uploads/Karkasson_solo_web.pdf",   "name": "Соло-режим" }
        ],
        "gallery": [
          "https://media.lavkaigr.ru/cache/63/d1/63d1940c2a20241e0845b845c718e18a.png",
          "https://media.lavkaigr.ru/cache/65/f5/65f58aceb28a79f70e29539904266a57.png",
          "https://media.lavkaigr.ru/cache/38/76/38761ccca5be8e37733dcac607221af9.png",
          "https://media.lavkaigr.ru/cache/5a/8a/5a8a50e299016a496d4c40beb6d409ba.png",
          "https://media.lavkaigr.ru/cache/f2/0c/f20c3ed821e9800460324fa98e44098e.png",
          "https://media.lavkaigr.ru/cache/d2/a9/d2a957a8ed643d5cc8e268a5784aa229.png",
          "https://media.lavkaigr.ru/cache/f1/57/f1570ac217817d950f07f66a9d93895c.png",
          "https://media.lavkaigr.ru/cache/19/47/1947d8401c5951de86bdba639efdf82c.png",
          "https://media.lavkaigr.ru/cache/ec/e5/ece54d872eb2a8d94e043ed635418679.png",
          "https://media.lavkaigr.ru/cache/db/4c/db4c71b1f22106a20bc8b476fd7bc233.png",
          "https://media.lavkaigr.ru/cache/cb/cb/cbcb019f3d32cdef66c99a7958b83aa1.png",
          "https://media.lavkaigr.ru/cache/b5/2c/b52c8f11914127788434e0e63f5d7e87.png",
          "https://media.lavkaigr.ru/cache/cf/1f/cf1f60d09f8da2a0dbcc9ca92b7a4d00.png",
          "https://media.lavkaigr.ru/cache/b1/85/b18557c1a1680b1ddeef541cc7c1163d.png",
          "https://media.lavkaigr.ru/cache/d8/8a/d88aa866b58fa9dd09f2e6e7f6f6085c.png",
          "https://media.lavkaigr.ru/cache/94/b8/94b82f790d76e8452906731e35f1fa87.png",
          "https://media.lavkaigr.ru/cache/6e/2b/6e2b5a89b4fbb37a54e04e6bd0e36679.png",
          "https://media.lavkaigr.ru/cache/e4/0b/e40bd920646d04bc92e05980fec07266.png",
          "https://media.lavkaigr.ru/cache/d4/b0/d4b03a54e747193b3f51decde5b907ab.png"
        ],
        "composition": [
          "Каркассон (2019)",
          "72 квадрата участков земли;",
          "40 фишек 5-ти цветов;",
          "Поле шкалы подсчёта очков;",
          "Правила игры."
        ]
      }
    }
  ]
}
```

> **Лавка Игр-специфика:**
> - `extra.tags` — игровые механики (есть не у всех игр)
> - `extra.category` — slug категории из URL (`"family"`, `"strategicheskie"`, `"abstraktnye"` и т.д.)
> - `extra.rules` — массив объектов `{url, name}` с именованными PDF
> - `extra.gallery` — 19 thumbnail-изображений (~480px), все одного товара

### `/search?q=Каркассон&stores=gaga&limit=1`

```json
{
  "source": "network",
  "errors": {},
  "products": [
    {
      "id": 3,
      "store_slug": "gaga",
      "title": "Каркассон. Средневековье (Новое Издание)",
      "price_rub": 1990.0,
      "url": "https://gaga.ru/game/carcassonne/",
      "image_url": "https://gaga.ru/gaga/files/images/main/4814.png",
      "image_url_hd": "https://gaga.ru/gaga/files/images/fullsize/4814/1.jpg",
      "description": "Каркассон (Carcassonne) и другие настольные игры ждут вас в нашем каталоге — Самовывоз, доставка курьером — Узнайте больше на сайте",
      "players": "2-5",
      "age_min": 7,
      "playtime": "0.5 - 1.5 ч.",
      "rules_url": "https://gaga.ru/gaga/files/pdf/rules/ru/4814.pdf",
      "fetched_at": "2026-05-06T19:37:39.431517+00:00",
      "extra": {
        "complexity": "правила простые",
        "rating": "5",
        "review_count": "12",
        "offline_price": 234000,
        "gallery": [
          "https://gaga.ru/gaga/files/images/fullsize/4814/1.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/8.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/7.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/9.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/3.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/4.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/2.jpg",
          "https://gaga.ru/gaga/files/images/fullsize/4814/6.jpg"
        ],
        "rules": [
          "https://gaga.ru/gaga/files/pdf/rules/ru/4814.pdf",
          "https://gaga.ru/gaga/files/pdf/rules/ru/4814-426681.pdf"
        ],
        "dimensions": "27.7см x 19.4см x 6.7см",
        "composition": "Состав:• 72 квадрата местности • дорожка подсчёта очков • 40 фишек подданных • правила игры Состав дополнений: • 5 фишек аббатов • 12 квадратов с рекой"
      }
    }
  ]
}
```

> **GaGa-специфика:**
> - `extra.rating` — строка, рейтинг из 5 звёзд по голосам пользователей
> - `extra.review_count` — строка, количество отзывов
> - `extra.offline_price` — цена в **копейках** (без регистрации, выше онлайн-цены); `234000` = 2340 руб.
> - `extra.gallery` — fullsize-фотографии товара (нумерованные: `1.jpg`, `2.jpg`, …)
> - `extra.rules` — массив строк-URL (в отличие от Лавки, где `[{url, name}]`)
> - `extra.complexity` — словесная оценка: `"правила простые"` / `"правила средние"` / `"правила сложные"`
> - `extra.dimensions` — размеры коробки; `extra.weight` — вес (если указан на сайте)

### `/search?q=Каркассон&stores=hobbygames&limit=1`

```json
{
  "source": "network",
  "errors": {},
  "products": [
    {
      "id": 4,
      "store_slug": "hobbygames",
      "title": "Каркассон",
      "price_rub": 1990.0,
      "url": "https://hobbygames.ru/karkasson",
      "image_url": "https://hobbygames.ru/image/cache/hobbygames_beta/data/HobbyWorld/Karkasson/2022/carcassonne_2022_00.jpg",
      "image_url_hd": "https://hobbygames.ru/image/data/HobbyWorld/Karkasson/2022/carcassonne_2022_00.jpg",
      "description": "Легенда в новом виде",
      "players": null,
      "age_min": null,
      "playtime": null,
      "rules_url": "https://hobbygames.ru/download/rules/Carcassonne2019_Rules.pdf",
      "fetched_at": "2026-05-06T19:18:49.679538+00:00",
      "extra": {
        "availability": true,
        "category": "Семейные игры",
        "sku": "UT-00018963",
        "rules": [
          "https://hobbygames.ru/download/rules/Karkasson_solo_web.pdf",
          "https://hobbygames.ru/download/rules/Carcassonne2019_Rules.pdf"
        ],
        "gallery": [
          "https://hobbygames.ru/image/data/HobbyWorld/Karkasson/2022/carcassonne_2022_00.jpg",
          "https://hobbygames.ru/image/cache/hobbygames_beta/data/HobbyWorld/Karkasson/2022/carcassonne_2022_00-1980x1980-wm.webp",
          "https://hobbygames.ru/image/cache/hobbygames_beta/data/HobbyWorld/Karkasson/2022/HG/Karkasson_2022_01-1980x1980-wm.webp",
          "https://hobbygames.ru/image/cache/hobbygames_beta/data/HobbyWorld/Karkasson/2022/HG/Karkasson_2022_02-1980x1980-wm.webp",
          "https://hobbygames.ru/image/cache/hobbygames_beta/data/HobbyWorld/Karkasson/2022/HG/Karkasson_2022_03-1980x1980-wm.webp"
        ]
      }
    }
  ]
}
```

> **HobbyGames-специфика:**
> - `players`, `age_min`, `playtime` — всегда `null` (данные не предоставляет)
> - `extra.availability` — `true` если товар в наличии
> - `extra.sku` — артикул товара (e.g. `"UT-00018963"`)
> - `extra.gallery` — содержит одно фото в нескольких размерах (`-100x100`, `-480x480`, `-1980x1980-wm`) плюс обложки дополнений к игре; всего 30–40 URL

---

### `/history/1`

```json
[
  { "price": 185000, "fetched_at": "2026-04-10T12:00:00.000000+00:00" },
  { "price": 199000, "fetched_at": "2026-05-06T18:47:58.722698+00:00" }
]
```

> Цена в копейках: `185000 / 100 = 1850 руб.`

---

## Советы для разработчика web-приложения

### Null-safety

Поля `image_url`, `image_url_hd`, `description`, `players`, `age_min`, `playtime`, `rules_url` могут быть `null`. Проверяйте перед использованием:

```javascript
// Хорошо
const img = product.image_url_hd ?? product.image_url ?? '/placeholder.png';

// Для числовых полей
const age = product.age_min != null ? `от ${product.age_min} лет` : '';
```

### Галерея

`extra.gallery` — массив URL. Может быть пустым `[]` или отсутствовать:

```javascript
const gallery = product.extra?.gallery ?? [];
```

### Сортировка по цене

`price_rub` — всегда число (float). Безопасно для `.sort()`:

```javascript
products.sort((a, b) => a.price_rub - b.price_rub);
```

### Фильтр по игрокам

`players` — строка вида `"2-5"`. Для фильтрации нужен парсинг:

```javascript
function parsePlayerRange(players) {
  if (!players) return null;
  const [min, max] = players.split('-').map(Number);
  return { min, max: max ?? min };
}

// Фильтр: показать игры для 3 игроков
const filtered = products.filter(p => {
  const range = parsePlayerRange(p.players);
  return range && range.min <= 3 && range.max >= 3;
});
```

### История цен (конвертация копеек)

```javascript
const history = await fetch(`/history/${product.id}`).then(r => r.json());
const chartData = history.map(point => ({
  date: new Date(point.fetched_at),
  price: point.price / 100,  // копейки → рубли
}));
```

### Отображение рейтинга (только GaGa)

```javascript
const rating = product.extra?.rating;      // "4.8" или undefined
const count  = product.extra?.review_count; // "12" или undefined

if (rating) {
  console.log(`★ ${rating} (${count} отзывов)`);
}
```

### Ссылка на скачивание правил

```javascript
if (product.rules_url) {
  // Прямой PDF
  window.open(product.rules_url, '_blank');
}

// Все правила из extra (у Лавки — объекты {url, name}, у GaGa — строки)
const allRules = product.extra?.rules ?? [];
```
