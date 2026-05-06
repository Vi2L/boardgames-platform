# Поля данных парсеров — полный разбор

Что доступно на каждом сайте, и что из этого собирается.

**Обозначения:**
- ✅ — собирается, сохраняется в колонке таблицы `products`
- 📦 — собирается, сохраняется в `price_observations.raw_json` (поле `extra` в API)
- ❌ — недоступно на сайте

**Архитектура сбора:**
Каждый парсер делает два параллельных этапа:
1. Страница поиска → список товаров (базовые поля)
2. Страница каждого товара → обогащение (детальные поля), параллельно через `asyncio.gather`

---

## HobbyGames (hobbygames.ru)

Работает с любого IP. Геоблок снят.

**Технология поиска**: `GET /catalog/search?keyword=<текст>` → HTML со встроенным JSON-LD `ItemList`  
**Технология детальной страницы**: `GET /<slug>/` → HTML + JSON-LD `Product`

### Страница поиска (`/catalog/search?keyword=...`)

Данные берутся из **JSON-LD `ItemList`** — HTML-парсинг не нужен.  
Числовой `external_id` — из атрибута `data-product_id` карточек `.product-card`.

| Поле | Источник | Статус |
|------|----------|--------|
| Название | JSON-LD `"name"` | ✅ |
| URL товара | JSON-LD `"url"` | ✅ |
| External ID | `<div data-product_id="...">` → fallback: slug из URL | ✅ |
| Цена | JSON-LD `offers.price` (в рублях) | ✅ |
| Изображение (thumbnail) | JSON-LD `"image"` + базовый URL кеша | ✅ |
| Описание (краткое) | JSON-LD `"description"` | ✅ |
| Наличие | JSON-LD `offers.availability` (`InStock`) | 📦 `raw["availability"]` |

### Страница товара (`/<slug>/`)

| Поле | Источник | Статус |
|------|----------|--------|
| Изображение HD | `og:image` — полный абсолютный URL | ✅ |
| Описание | JSON-LD Product `"description"` | ✅ |
| Категория | JSON-LD Product `"category"` | 📦 `raw["category"]` |
| SKU | JSON-LD Product `"sku"` | 📦 `raw["sku"]` |
| Правила PDF | `<a href="/download/rules/...pdf">` | ✅ |
| Галерея | `"https://hobbygames.ru/image/..."` из страницы | 📦 `raw["gallery"]` |
| Кол-во игроков | нет в структурированных данных | ❌ |
| Возраст | нет в структурированных данных | ❌ |
| Время партии | нет в структурированных данных | ❌ |
| Рейтинг / отзывы | на странице есть, не в JSON-LD | ❌ |
| Состав | нет структурированных данных | ❌ |

**Реальные данные (Каркассон):**
```
external_id="72557" (числовой data-product_id)
price=1990 руб. | in_stock=True
rules_url="https://hobbygames.ru/download/rules/Carcassonne2019_Rules.pdf"
image_url_hd="https://hobbygames.ru/image/data/HobbyWorld/Karkasson/2022/..."
raw["category"]="Семейные игры" | raw["sku"]="UT-00018963"
```

---

## Лавка Игр (lavkaigr.ru)

**Технология поиска**: `GET /shop/search/?query=<текст>` → HTML (Django SSR, UTF-8)  
**Технология детальной страницы**: `GET /shop/<категория>/<slug>/` → HTML

### Страница поиска

| Поле | Источник | Статус |
|------|----------|--------|
| Название | `<a class="game-name">` | ✅ |
| URL товара | `href` ссылки | ✅ |
| External ID | `<div class="photo-block" data-id="...">` | ✅ |
| Цена | `<a data-price="...">` на кнопке «Купить» | ✅ |
| Изображение (thumbnail) | `<img class="unveil" data-src="...">` | ✅ |

### Страница товара (`/shop/<категория>/<slug>/`)

| Поле | Источник | Статус |
|------|----------|--------|
| Изображение HD | `og:image` (`media.lavkaigr.ru/catalog/...jpg`) | ✅ |
| Описание | `og:description` | ✅ |
| Кол-во игроков | `<i class="fa-male"></i>...<strong>2-5</strong>` | ✅ |
| Минимальный возраст | `<i class="fa-child"></i>...<strong>от 8 лет</strong>` | ✅ |
| Время партии | `<i class="fa-clock-o"></i>...<strong>30-45 мин.</strong>` | ✅ |
| Правила PDF | `<a href="...pdf">Правила</a>` (основной файл) | ✅ |
| Категория | из URL-пути `/shop/<категория>/` | 📦 `raw["category"]` |
| Механики / теги | `<a href="/shop/tag/...">` | 📦 `raw["tags"]` |
| Время на освоение | `<i class="fa-..."></i>Время на освоение...` | 📦 `raw["complexity"]` |
| Язык | `<i>Язык...</i><strong>Русский</strong>` | 📦 `raw["language"]` |
| Все правила PDF | полный список файлов | 📦 `raw["rules"]` |
| Галерея (до ~19 фото) | `<img class="unveil" data-src="...lavkaigr...">` | 📦 `raw["gallery"]` |
| Состав игры | `<li>72 квадрата...</li>` | 📦 `raw["composition"]` |
| Рейтинг / отзывы | нет на сайте | ❌ |
| Наличие | нет явных данных | ❌ |
| Издатель / автор | нет в разметке | ❌ |

**Реальные данные (Каркассон 2019):**
```
players="2-5" | age_min=8 | playtime="30-45 мин."
rules_url="https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf"
gallery=19 изображений
tags=["выкладывание плиток", "управление областями"]
```

---

## GaGa.ru (gaga.ru)

**Технология поиска**: `GET /search/?word=<cp1251-encoded>` → HTML (PHP, **charset=cp1251**)  
**Технология детальной страницы**: `GET /game/<slug>/` → HTML (cp1251)

> httpx автоматически декодирует cp1251 по заголовку `Content-Type`. Поисковый запрос кодируется через `urllib.parse.quote(query.encode('cp1251'))`.

### Страница поиска

| Поле | Источник | Статус |
|------|----------|--------|
| Название | `<a class="preview-card__title" title="...">` | ✅ |
| URL товара | `href` ссылки (`/game/<slug>/`) | ✅ |
| External ID | `<button data-gid="...">` | ✅ |
| Онлайн-цена | `<span itemprop="price">` / `data-price` | ✅ |
| Изображение (thumbnail) | `<img src="/gaga/files/images/main/<id>.png">` | ✅ |

### Страница товара (`/game/<slug>/`)

| Поле | Источник | Статус |
|------|----------|--------|
| Изображение HD | `og:image` (`/gaga/files/images/fullsize/<id>/1.jpg`) | ✅ |
| Описание | `<div class="game-description">` → fallback `og:description` | ✅ |
| Кол-во игроков | `<ul class="card-features__list"><li>2-5 игроков</li>` | ✅ |
| Минимальный возраст | `<li>от 7 лет</li>` | ✅ |
| Время партии | `<li>0.5 - 1.5 ч.</li>` | ✅ |
| Правила PDF | `/gaga/files/pdf/rules/ru/<id>.pdf` (основной) | ✅ |
| Сложность правил | `<li>правила простые/средние/сложные</li>` | 📦 `raw["complexity"]` |
| Рейтинг (из 5) | `itemprop="ratingValue"` | 📦 `raw["rating"]` |
| Количество отзывов | `itemprop="reviewCount"` | 📦 `raw["review_count"]` |
| Место в рейтинге сайта | `<a href="/rating/#game...">3 место</a>` | 📦 `raw["ranking"]` |
| Офлайн-цена (без рег.) | `<span class="offline-price__value">` | 📦 `raw["offline_price"]` (копейки) |
| Галерея (до 8+ fullsize) | `/gaga/files/images/fullsize/<id>/<n>.jpg` | 📦 `raw["gallery"]` |
| Все правила PDF | полный список | 📦 `raw["rules"]` |
| Размеры коробки | `Высота х Ширина х Глубина: 27.7см x...` | 📦 `raw["dimensions"]` |
| Вес | `Вес: 900 гр.` | 📦 `raw["weight"]` |
| Состав | текст после «Состав:» | 📦 `raw["composition"]` |
| Издатель / автор | не вынесен в атрибут | ❌ |
| Наличие по магазинам | список адресов (динамически) | ❌ |

**Реальные данные (Каркассон. Средневековье):**
```
players="2-5" | age_min=7 | playtime="0.5 - 1.5 ч."
rules_url="https://gaga.ru/gaga/files/pdf/rules/ru/4814.pdf"
gallery=8 изображений (fullsize)
raw["rating"]="4.8" | raw["review_count"]="12"
raw["offline_price"]=234000 (2340 руб.)
```

---

## Схема БД

```
products
├── id, store_slug, external_id, title, normalized_title, url
├── image_url       — thumbnail со страницы поиска
├── image_url_hd    — ✅ HD-изображение со страницы товара
├── description     — ✅ описание игры
├── players         — ✅ кол-во игроков, e.g. "2-5"
├── age_min         — ✅ минимальный возраст (int)
├── playtime        — ✅ время партии, e.g. "30-45 мин"
└── rules_url       — ✅ основной PDF правил

price_observations
├── product_id, price (копейки), fetched_at
└── raw_json        — 📦 gallery, tags, rating, dimensions и т.д.
```

Поля в `products` обновляются через `COALESCE(excluded.value, existing_value)` — существующее значение не перезаписывается `NULL` если новый парсинг вернул пустое.

---

## API ответ `/search`

```json
{
  "source": "network",
  "errors": {},
  "products": [{
    "id": 1,
    "store_slug": "lavkaigr",
    "title": "Каркассон (2019)",
    "price_rub": 1990.0,
    "url": "https://www.lavkaigr.ru/shop/family/karkasson-2019/",
    "image_url": "https://media.lavkaigr.ru/cache/.../thumb.png",
    "image_url_hd": "https://media.lavkaigr.ru/catalog/karkasson.jpg",
    "description": "Вы — феодальный правитель...",
    "players": "2-5",
    "age_min": 8,
    "playtime": "30-45 мин.",
    "rules_url": "https://media.lavkaigr.ru/uploads/Carcassonne2019_Rules.pdf",
    "fetched_at": "2026-05-06T16:30:00+00:00",
    "extra": {
      "category": "family",
      "tags": ["выкладывание плиток", "управление областями"],
      "gallery": ["https://media.lavkaigr.ru/cache/.../1.png", "..."],
      "rules": [{"url": "...pdf", "name": "Правила"}],
      "language": "Русский",
      "complexity": "3 мин",
      "composition": ["72 квадрата местности;", "40 фишек подданных;"]
    }
  }]
}
```
