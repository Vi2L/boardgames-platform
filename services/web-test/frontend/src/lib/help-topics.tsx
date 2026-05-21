/**
 * help-topics.tsx — typed-словарь контекстных help-боксов.
 *
 * Используется компонентом `<HelpBox topic="..." />` (см.
 * `components/shared/HelpBox.tsx`). Тип `TopicId` выводится из ключей —
 * передача несуществующего topic в HelpBox даёт ошибку компиляции.
 *
 * **Чек-лист добавления нового топика** (см. `frontend/CLAUDE.md`,
 * секция «Help-контент»):
 * 1. Добавить запись в `HELP_TOPICS` с ключом `domain.concept_name`.
 * 2. Тип `TopicId` обновится автоматически.
 * 3. Вставить `<HelpBox topic="domain.concept_name" />` рядом с концептом
 *    в нужном компоненте.
 * 4. Запустить `npx tsc --noEmit` — гарантируется, что все вызовы валидны.
 *
 * Содержимое (`body`) — JSX-фрагменты. Markdown намеренно не используется
 * (см. комментарий в `components/matching/MatchingHelpTab.tsx`): JSX даёт
 * type-safe ссылки, code-блоки и переиспользование компонентов вроде
 * `<TierChip>` без bundle-stuffing'а react-markdown'ом.
 */
import { type ReactNode } from 'react'

interface HelpTopic {
  /** Заголовок popover'а. Краткий, без точки в конце. */
  title: string
  /** Тело: 2-6 предложений JSX. Допустимы `<code>`, `<strong>`, `<a>`. */
  body: ReactNode
  /** Опциональная ссылка «подробнее». href может быть external или `/route`. */
  learnMore?: { label: string; href: string }
}

/**
 * Хелпер сохраняет узкие литералы ключей (для `TopicId = keyof typeof`),
 * но проверяет, что значения — корректный `HelpTopic` (включая опциональный
 * `learnMore`, который `satisfies` иначе обрезает narrowing'ом).
 */
function defineTopics<K extends string>(t: Record<K, HelpTopic>): Record<K, HelpTopic> {
  return t
}

// ─── Словарь ────────────────────────────────────────────────────────────────

export const HELP_TOPICS = defineTopics({
  // ── /matching ─────────────────────────────────────────────────────────────

  'matching.tier_t0': {
    title: 'T0 — кеш match_decisions',
    body: (
      <>
        Первый tier матчинга: lookup в таблице{' '}
        <code className="text-indigo-300">match_decisions</code> по
        нормализованному title (NFKD + lower). Если запись есть и не
        протухла — мгновенный hit без обращения к pg_trgm и LLM. TTL зависит
        от источника: <code>manual=∞</code>, <code>auto_t1=30д</code>,{' '}
        <code>auto_t2=14д</code>, <code>auto_t3=7д</code>. Negative cache
        (game_id=null от reject/LLM) тоже работает — повторный ingest того
        же title отсекается на T0.
      </>
    ),
  },

  'matching.tier_t1': {
    title: 'T1 — pg_trgm триграммы',
    body: (
      <>
        Триграммный поиск через PostgreSQL <code>pg_trgm</code>. Сравнивает{' '}
        <code>title_norm</code> оффера с <code>title</code> /{' '}
        <code>title_ru</code> + все <code>game_aliases</code> через UNION
        c MAX(score). Порог auto-матча — <code>0.92</code> (примерно одна
        опечатка). Синхронно в ingest'е. Добавление нового alias
        немедленно повышает hit-rate без переиндексации.
      </>
    ),
  },

  'matching.tier_t2': {
    title: 'T2 — bge-m3 семантика',
    body: (
      <>
        Семантический матч через <code>bge-m3</code> embeddings + pgvector.
        Cosine ≥ <code>0.85</code> и разрыв со вторым кандидатом ≥{' '}
        <code>0.05</code> (confidence margin) → auto. Работает асинхронно в{' '}
        <code>match_worker</code>. Требует прогретой таблицы{' '}
        <code>game_embeddings</code> — если пустая, tier не даёт матчей.
        Запусти warmup: <strong>Контроль → Прогреть эмбеддинги</strong>.
      </>
    ),
  },

  'matching.tier_t3': {
    title: 'T3 — LLM-арбитр',
    body: (
      <>
        Включается только при <code>vec_ambiguous</code>: ≥2 кандидата с
        cosine ≥ 0.70 близко друг к другу. LLM (<code>qwen2.5:7b</code>)
        получает кандидатов и решает, кому отдать матч. JSON-ответ:{' '}
        <code>{`{"game_id": N, "confidence": 0..1}`}</code> или{' '}
        <code>{`{"game_id": null, "reason": "not_a_boardgame: ..."}`}</code>.
        Auto-match при confidence ≥ <code>0.75</code>. Самый медленный
        tier (~1-3с), но самый точный на сложных случаях.
      </>
    ),
  },

  'matching.kill_switch': {
    title: 'ML kill-switch',
    body: (
      <>
        Runtime-flag <code>ml_enabled</code> в БД (миграция 0013).
        Выключает <strong>только T2+T3</strong> — T0 cache и T1 pg_trgm
        продолжают работать (это синхронный код без зависимости от Ollama).
        Используй при инциденте Ollama / pgvector, чтобы не копить
        skipped-очередь. TTL-кеш ≤5с — изменение пропагируется на все
        catalog-инстансы.
      </>
    ),
  },

  'matching.circuit_breaker': {
    title: 'Circuit Breaker (Ollama-модели)',
    body: (
      <>
        Per-model breaker (bge-m3, qwen2.5). После{' '}
        <strong>3 подряд провалов</strong> цепь открывается — воркер
        перестаёт слать запросы. Через <strong>60с</strong> → half-open:
        следующий запрос-probe. Успешный закрывает цепь, провал —
        снова открывает. Не путать с per-store breaker'ом в parsers
        (тот про rate-limit, см. <code>parsers/utils/breaker.py</code>).
      </>
    ),
  },

  'matching.worker_interval': {
    title: 'Worker interval',
    body: (
      <>
        <code>match_worker</code> — APScheduler interval-job. Каждые N
        секунд берёт batch <code>limit=32</code> из{' '}
        <code>match_queue</code> через <code>FOR UPDATE SKIP LOCKED</code>{' '}
        (параллельные тики не конкурируют). Default <code>10с</code>.
        Уменьши при большом бэклоге, поставь 30-60с для снижения
        нагрузки на Ollama при фоновой работе.
      </>
    ),
  },

  'matching.skipped_reasons': {
    title: 'Skipped — почему и как re-enqueue',
    body: (
      <>
        Skipped — <strong>конечный</strong> статус: воркер сам не подберёт.
        Имеет смысл re-enqueue только при изменении условий:
        <ul className="list-disc list-inside mt-1.5 space-y-0.5">
          <li><code>llm_unavailable</code> → после восстановления Ollama</li>
          <li><code>no_candidates</code> → после warmup / импорта BGG</li>
          <li><code>vec_below_threshold</code> → после правки alias'ов</li>
          <li><code>ml_no_match</code>, <code>llm_low_confidence</code> →{' '}
            переноси в ручную очередь, не re-enqueue</li>
        </ul>
      </>
    ),
  },

  // ── /catalog → Очередь ────────────────────────────────────────────────────

  'catalog.bucket_good': {
    title: 'Bucket «good»',
    body: (
      <>
        Офферы со score ≥ <code>auto_threshold</code> (обычно 0.85-0.92).
        Зелёная зона: высокая вероятность правильного матча. Самый быстрый
        ручной workflow — один клик «Связать» подтверждает предложение
        воркера. Стоит проверять в первую очередь — высокий ROI на минуту
        оператора.
      </>
    ),
  },

  'catalog.bucket_candidate': {
    title: 'Bucket «candidate»',
    body: (
      <>
        Score между <code>candidate_threshold</code> и{' '}
        <code>auto_threshold</code>. Жёлтая зона: воркер нашёл кандидата,
        но недостаточно уверен для авто-матча. Требует осознанной проверки
        оператора — обычно тут «почти то же название» или есть
        конкурирующий кандидат.
      </>
    ),
  },

  'catalog.bucket_cold': {
    title: 'Bucket «cold»',
    body: (
      <>
        Score ниже <code>candidate_threshold</code> (обычно &lt;0.30).
        Серая зона: воркер не нашёл близкого совпадения. Возможные
        причины: (1) игры нет в каталоге — импортируй через BGG/Tesera;
        (2) неканоничное название — добавь alias к существующей игре;
        (3) это не игра (книга/мерч) — кликни Reject.
      </>
    ),
  },

  'catalog.match_status_values': {
    title: 'match_status — что значит каждый',
    body: (
      <>
        Статус оффера в матчинге:
        <ul className="list-disc list-inside mt-1.5 space-y-0.5">
          <li><code>unmatched</code> — не обработан или нет кандидата</li>
          <li><code>auto</code> — матч через T0-T3 без оператора</li>
          <li><code>manual</code> — оператор привязал вручную</li>
          <li><code>rejected</code> — оператор отклонил (не игра / дубль)</li>
          <li><code>skipped</code> — воркер остановился (см. <code>skip_reason</code>)</li>
        </ul>
        <code>manual</code> и <code>rejected</code> — финальные:
        reassess их не трогает.
      </>
    ),
  },

  // ── /bgg-sync → Расписание ────────────────────────────────────────────────

  'bgg_sync.bgg_top_sync': {
    title: 'BGG Top Sync — недельный',
    body: (
      <>
        Обогащает BGG Top-N играми из XML API. Обновляет rank,
        bayes_average, designers, mechanics, statistics, polls. При
        rate-limit 1 req/sec — топ-1000 за ~17 минут. Дефолтный cron —
        еженедельно (вс 03:00 UTC). Запускай вручную после массового
        добавления игр в каталог или CSV-seed'а.
      </>
    ),
  },

  'bgg_sync.bgg_hotness_sync': {
    title: 'BGG Hotness — горячий список',
    body: (
      <>
        Скачивает BGG Hotness API — топ-50 «горячих» игр сейчас (один
        быстрый запрос). Сохраняет снимок в <code>bgg_hotness_snapshots</code>{' '}
        — история позволяет смотреть тренды попадания в топ. Дефолт —
        раз в 6 часов.
      </>
    ),
  },

  'bgg_sync.bgg_mini_batch': {
    title: 'BGG Mini-batch — догонка по одной',
    body: (
      <>
        Точечное обогащение через BGG XML по одной игре (per-item).
        Запускается для игр с <code>source='csv-ranks'</code>, у которых
        нет description / designers / mechanics. Безопасен для BGG
        rate-limit — 1 req/sec встроен. Полезен для «догонки» после
        seed'а из CSV (162K игр) — top'ы делает <code>bgg_top_sync</code>,
        остальное точечно догоняет mini_batch.
      </>
    ),
  },

  'bgg_sync.bgg_family_refresh': {
    title: 'BGG Family Refresh — семейства игр',
    body: (
      <>
        Обновляет BGG Families — серии и связанные группы (например, все
        игры Каркассона). Таблица <code>bgg_families</code> + связь через{' '}
        <code>bgg_family_members</code> (миграция 0019). При{' '}
        <code>bgg_family_cascade_enabled=true</code> при импорте новой
        игры её семьи автоматически догружаются. Дефолт — раз в неделю
        (вс 05:00 UTC).
      </>
    ),
  },

  'bgg_sync.bgg_yearly_releases': {
    title: 'BGG Yearly Releases — новинки года',
    body: (
      <>
        Импортирует свежие игры текущего года из BGG (HTML scraper по
        фильтру <code>yearpublished=YYYY&sort=numvoters</code> — XML API
        не отдаёт обе оси одновременно). Обнаруживает игры, которых ещё
        нет в каталоге. После прогона проверь «Без BGG ID» на новые
        unmatched записи. Дефолт — 1-е число месяца, 02:00 UTC.
      </>
    ),
  },

  'bgg_sync.retention_params': {
    title: 'Параметры job’а',
    body: (
      <>
        <code>retention_days</code> — сколько дней хранить историю в
        целевой таблице (для <code>match_log_retention</code> — 90 дней
        активных auto-матчей сохраняются независимо от возраста).{' '}
        <code>rate_limit_sec</code> — минимальный интервал между
        запросами к BGG API. <strong>BGG банит при &lt;0.5 req/sec</strong>,
        не уменьшай ниже без необходимости.
      </>
    ),
  },

  // ── /debug → Контракт ─────────────────────────────────────────────────────

  'debug.coverage_heatmap': {
    title: 'Coverage heatmap',
    body: (
      <>
        Показывает, какие опциональные поля <code>ParsedProduct</code>{' '}
        стабильно заполняет каждый магазин (% непустых значений в БД).
        <strong> Красные ячейки</strong> — поле почти всегда пустое у
        этого магазина; <strong>зелёные</strong> — надёжный сигнал.
        Используй при добавлении нового магазина или после правки
        селекторов парсера — регрессия покажется падением coverage.
      </>
    ),
  },

  'debug.parsed_product_required': {
    title: 'Required-поля ParsedProduct',
    body: (
      <>
        Required: <code>external_id</code>, <code>title</code>,{' '}
        <code>url</code>. Без них оффер отклоняется catalog'ом ещё до
        матчинга. <code>price</code> — optional: <code>null</code>{' '}
        обычно означает «нет в наличии» (для большинства магазинов).
        Остальные поля (<code>image_url</code>, <code>players</code>,{' '}
        <code>playtime</code>) — bonus; coverage по ним показывает heatmap.
      </>
    ),
  },

  'debug.field_defaults': {
    title: 'Defaults опциональных полей',
    body: (
      <>
        Defaults: <code>extra={'{}'}</code> (пустой dict),{' '}
        <code>category=null</code> (определяется парсером),{' '}
        <code>in_stock=null</code> (неизвестно). Catalog при ingest
        пытается извлечь <code>sku</code> / <code>availability</code> /{' '}
        <code>in_stock</code> из <code>extra</code>, если явные поля не
        заданы — это legacy-совместимость с HobbyGames и CrowdGames.
      </>
    ),
  },

  'debug.category_whitelist': {
    title: 'Category whitelist',
    body: (
      <>
        Catalog принимает только офферы с <code>category</code> в whitelist:{' '}
        <code>boardgames</code> | <code>expansion</code> |{' '}
        <code>accessory</code> | <code>null</code>. Офферы вне whitelist
        дропаются до upsert — счётчик возврата{' '}
        <code>skipped_category</code> в ответе{' '}
        <code>POST /ingest/offers</code>. <code>null</code> — legacy для
        старых парсеров без поля.
      </>
    ),
  },

  // ── /dlq ──────────────────────────────────────────────────────────────────

  'dlq.what_is_dlq': {
    title: 'Что такое DLQ',
    body: (
      <>
        Dead-Letter Queue — буфер батчей от parsers, которые catalog не
        принял (downtime / 5xx / timeout). Parsers сохраняет неудачный
        payload в SQLite-таблицу <code>catalog_dlq</code> вместо потери
        данных. После восстановления catalog нажми <strong>Replay all</strong>{' '}
        — все зависшие батчи переотправятся; при успехе запись удаляется
        из DLQ.
      </>
    ),
  },

  'dlq.replay_vs_delete': {
    title: 'Replay vs Delete',
    body: (
      <>
        <strong>Replay</strong> — повторная отправка payload в{' '}
        <code>POST /ingest/offers</code>. При успехе запись удаляется,
        при ошибке <code>attempt_count</code> растёт.{' '}
        <strong>Delete</strong> — отказ от данных без попытки.{' '}
        Удаляй <strong>только</strong> если батч устарел и цены уже
        неактуальны. Undo нет.
      </>
    ),
  },

  'dlq.attempt_count': {
    title: 'attempt_count',
    body: (
      <>
        Сколько раз parsers пытался отправить этот батч. Высокий счётчик
        (&gt;5) означает либо длительный downtime catalog, либо постоянную
        ошибку валидации payload. Проверь <code>last_error</code> перед
        replay — если там <code>422 Validation</code>, повторная отправка
        не поможет, нужна правка producer'а (<code>parsers/catalog_publisher.py</code>).
      </>
    ),
  },
})

// ─── Type-safe API ──────────────────────────────────────────────────────────

/**
 * Все известные topic-ID. Расширяется автоматически при добавлении ключа
 * в `HELP_TOPICS`. Несуществующий topic в <HelpBox /> = TS-ошибка.
 */
export type TopicId = keyof typeof HELP_TOPICS
