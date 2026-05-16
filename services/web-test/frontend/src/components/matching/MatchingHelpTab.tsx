/**
 * MatchingHelpTab — вкладка `/matching → Help`.
 *
 * Long-form документация для оператора. Reader-friendly layout с anchor
 * navigation слева и prose-content справа. Не использует react-markdown
 * (нет в проекте) — статичный JSX, что даёт стабильную типографику и
 * inline-кода с подсветкой.
 *
 * Полноценная справка по матчингу v2:
 *   - Архитектура pipeline (с ASCII-flow)
 *   - Когда вкл/выкл ML
 *   - Когда re-enqueue
 *   - Чтение match_log
 *   - Troubleshooting
 *   - Глоссарий
 */
import { useEffect, useState } from 'react'
import { Link2, AlertTriangle } from 'lucide-react'
import clsx from 'clsx'

import { TierChip } from './HowItWorks'
import { CircuitStateBadge } from './CircuitStateBadge'

// ── Anchor nav ────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: 'pipeline',   label: 'Архитектура pipeline' },
  { id: 'kill',       label: 'Когда ML вкл/выкл' },
  { id: 'reenqueue',  label: 'Когда re-enqueue' },
  { id: 'log',        label: 'Чтение match_log' },
  { id: 'troubles',   label: 'Troubleshooting' },
  { id: 'glossary',   label: 'Глоссарий' },
]

export function MatchingHelpTab() {
  const [active, setActive] = useState('pipeline')

  // Highlight current section in nav on scroll
  useEffect(() => {
    const onScroll = () => {
      for (const s of SECTIONS) {
        const el = document.getElementById(`mhelp-${s.id}`)
        if (!el) continue
        const r = el.getBoundingClientRect()
        if (r.top < 200 && r.bottom > 200) {
          setActive(s.id)
          break
        }
      }
    }
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    return () => document.removeEventListener('scroll', onScroll, { capture: true })
  }, [])

  return (
    <div className="flex gap-6">
      {/* Sticky sidebar nav */}
      <nav className="w-48 flex-shrink-0">
        <div className="sticky top-2 space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-gray-500 font-mono px-2 mb-2">
            on this page
          </div>
          {SECTIONS.map(s => (
            <a
              key={s.id}
              href={`#mhelp-${s.id}`}
              className={clsx(
                'block px-2 py-1 rounded text-[11px] transition-colors',
                active === s.id
                  ? 'bg-violet-950/40 text-violet-300 border-l-2 border-violet-500 -ml-px'
                  : 'text-gray-500 hover:text-gray-200 hover:bg-gray-900',
              )}
            >
              {s.label}
            </a>
          ))}
        </div>
      </nav>

      {/* Content */}
      <article className="flex-1 max-w-3xl prose-matching">
        <Section id="pipeline" title="Архитектура pipeline">
          <p>
            Матчер v2 — пятиуровневый pipeline. Каждый offer от парсера проходит
            tier'ы в порядке T0 → T1 → T2 → T3, первый дающий уверенный результат
            выигрывает. Если ни один не уверен — оффер уходит в T4 (manual queue).
          </p>

          <PipelineDiagram />

          <ul>
            <li>
              <TierChip tier="T0" /> <strong>cache hit.</strong> Таблица <code>match_decisions</code>:
              нормализованный title (NFKD lower) → game_id, с TTL per source (manual=∞, t1=30д, t2=14д, t3=7д).
              Sync, в ingest-роутере.
            </li>
            <li>
              <TierChip tier="T1" /> <strong>pg_trgm ≥ 0.92.</strong> Триграммный поиск по
              title/title_ru/aliases с UNION + MAX score. Sync. Порог 0.92 — фактически
              «опечатка в 1 букве».
            </li>
            <li>
              <TierChip tier="T2" /> <strong>bge-m3 cosine ≥ 0.85.</strong> Embedding query → pgvector top-K по
              <code>game_embeddings</code>. Если best ≥ 0.85 и второй кандидат значительно ниже
              (margin 0.05) — confident match. Async, в воркере. Без HNSW и эмбеддингов не работает.
            </li>
            <li>
              <TierChip tier="T3" /> <strong>qwen2.5:7b-instruct LLM-арбитр.</strong> Запускается только при
              <code>vec_ambiguous</code> (≥2 кандидата с score ≥ 0.70). LLM возвращает JSON с
              выбранным game_id и confidence. Auto-match если confidence ≥ 0.75.
            </li>
            <li>
              <TierChip tier="T4" /> <strong>manual queue.</strong> Оператор выбирает game вручную в
              <strong>/catalog → Очередь матчинга</strong>.
            </li>
          </ul>

          <SubHeading>Кто запускает T2+T3</SubHeading>
          <p>
            APScheduler-job <code>match_worker</code> тикает каждые 10 сек (interval, не cron).
            Берёт batch=32 через <code>FOR UPDATE SKIP LOCKED</code>, прогоняет каждый offer
            через T2 → возможно T3 → финализирует. При <code>OllamaUnavailable</code> возвращает
            запись в pending с exponential backoff (30→120→600→1800с).
          </p>

          <SubHeading>Circuit Breaker</SubHeading>
          <p className="flex items-center gap-2 flex-wrap">
            Для каждой Ollama-модели отдельно. После 3 подряд провалов цепь открывается:
            <CircuitStateBadge state="open" />
            Через 60 сек после последнего провала — half-open:
            <CircuitStateBadge state="half_open" />
            Первый успешный вызов закрывает обратно:
            <CircuitStateBadge state="closed" />
          </p>
        </Section>

        <Section id="kill" title="Когда ML вкл/выкл">
          <p>
            Kill-switch <code>ml_enabled</code> (Контроль → большой toggle) выключает <strong>только
            T2+T3</strong>. T0 cache и T1 trgm продолжают работать — это синхронный код в ingest.
          </p>
          <SubHeading>Выключай ML когда:</SubHeading>
          <ul>
            <li>Ollama флапает и забивает логи retry-сообщениями (Circuit Breaker уже спасает,
              но если флап постоянный — лучше выключить, чтобы воркер не пытался).</li>
            <li>Делаешь массовый ingest и хочешь чтобы parsers'ы не ждали enqueue (T2/T3 всё равно
              догонят асинхронно — но если очередь раздулась до 10К и хочешь сначала разгрести
              backlog).</li>
            <li>Тестируешь новую модель в Ollama, не хочешь чтобы catalog ходил в неё.</li>
          </ul>
          <SubHeading>Включай ML когда:</SubHeading>
          <ul>
            <li>Только что <code>ollama pull bge-m3</code> или <code>qwen2.5</code> — и убедился что
              ML-модели карточка показывает <CircuitStateBadge state="closed" /> .</li>
            <li>После warmup эмбеддингов — есть смысл re-enqueue skipped.</li>
            <li>Восстановил Ollama после рестарта macOS / Docker.</li>
          </ul>
        </Section>

        <Section id="reenqueue" title="Когда re-enqueue skipped">
          <p>
            Записи в статусе <code>skipped</code> — конечные: воркер их сам не подберёт. Re-enqueue
            возвращает их в pending. Имеет смысл если что-то поменялось:
          </p>
          <ul>
            <li><strong>llm_unavailable</strong> — после <code>ollama pull qwen2.5</code> и убедившись
              что модель отвечает (Контроль → ML-модели → closed). Re-enqueue все по этому фильтру.</li>
            <li><strong>no_candidates</strong> — после warmup эмбеддингов или массового импорта BGG/Tesera.
              Возможно теперь в каталоге есть похожая игра.</li>
            <li><strong>vec_below_threshold</strong> — после обогащения title_ru / aliases у конкретной
              игры. Текстовая близость могла подняться выше порога.</li>
            <li><strong>ml_no_match / llm_low_confidence</strong> — обычно НЕТ смысла re-enqueue:
              LLM уже сказал нет. Лучше отдать оператору в /catalog → Очередь.</li>
          </ul>
        </Section>

        <Section id="log" title="Чтение match_log">
          <p>
            Каждое изменение <code>offers.game_id</code> или <code>offers.match_status</code> пишет
            строку в <code>match_log</code>. Это аудит-журнал — точка истины «кто, когда, почему».
          </p>
          <SubHeading>Поля</SubHeading>
          <ul>
            <li><code>action</code>: <code>auto_t0/t1/t2/t3</code> (воркер сматчил автоматом по tier),
              <code>manual</code> (оператор привязал через /catalog), <code>reject</code> (оператор
              отметил как «не игра»), <code>unlink</code> (отмена manual link), <code>reassess</code>
              (batch-пересчёт), <code>revert</code> (откат другой записи).</li>
            <li><code>tier</code>: 0..3 — какой tier дал результат. Используется для статистики
              «сколько матчей сделал T2».</li>
            <li><code>prev_game_id / new_game_id</code>: что было до и после операции. При revert
              эти поля используются для восстановления.</li>
            <li><code>batch_id</code> (UUID): группировка для bulk-revert. Например, reassess-all
              получает один batch_id на всю операцию — можно откатить всё одним кликом.</li>
            <li><code>performed_by</code>: <code>worker</code>, <code>system</code>,
              <code>operator</code>, <code>api</code> (через X-API-Key).</li>
            <li><code>reverted_at</code>: если запись откачена — здесь timestamp. Полноценный
              «soft delete» — оригинальные prev/new сохраняются для аудита.</li>
          </ul>
          <SubHeading>Revert</SubHeading>
          <p>
            Три варианта:
          </p>
          <ul>
            <li><strong>Single revert</strong> (по одной строке): восстанавливает prev_game_id +
              prev_status у оффера. Опционально удаляет alias который был добавлен при матче
              (Shift+click в UI).</li>
            <li><strong>Bulk by ids</strong>: выбрал чекбоксами в журнале → revert. Идемпотентен
              (повторный bulk-revert не падает на уже откаченных).</li>
            <li><strong>Batch revert</strong>: по batch_id — откатывает целиком операцию (например,
              неудачный reassess-all). UUID берётся из любой строки batch'а.</li>
          </ul>
        </Section>

        <Section id="troubles" title="Troubleshooting">
          <SubHeading>Circuit Breaker открыт ("open")</SubHeading>
          <ol>
            <li>Контроль → ML-модели → смотрим failures count и last_check.</li>
            <li>Проверяем сам Ollama: <code>curl http://localhost:11434/api/tags</code> с хоста.</li>
            <li>Если Ollama жив — ждём, цепь сама перейдёт в half-open через 60с после последнего fail.</li>
            <li>Если Ollama мёртв — рестартим. После старта первый успешный probe закроет цепь.</li>
          </ol>

          <SubHeading>Warmup не идёт</SubHeading>
          <ol>
            <li>Контроль → нажми «Прогреть эмбеддинги». Запустится фоновый ImportJob.</li>
            <li>Смотрим прогресс в <strong>/bgg-sync → История</strong> с фильтром
              <code>type=warmup-embeddings</code>.</li>
            <li>Если падает на <code>ollama 503</code> — bge-m3 не загружен в Ollama. Сделай
              <code>ollama pull bge-m3</code>.</li>
            <li>Полный warmup на 162К игр занимает 1.5-4 часа на m1/m2 mac, под nohup.</li>
          </ol>

          <SubHeading>Очередь растёт</SubHeading>
          <ol>
            <li>Очередь → смотрим breakdown по статусам. Если pending &gt;&gt; processing — воркер
              не успевает.</li>
            <li>Проверяем интервал воркера (Контроль → match_worker → interval). По умолчанию 10с,
              можно поставить 5с при backlog.</li>
            <li>Если processing постоянно 0 — воркер не работает. Проверь scheduler-status
              (<strong>/bgg-sync → Расписание → match_worker</strong>).</li>
            <li>Если pending не уменьшается, а ml-модели <CircuitStateBadge state="open" /> — Ollama
              мёртв, никакая обработка не идёт.</li>
          </ol>

          <SubHeading>Skipped накопилось много</SubHeading>
          <p>
            Это нормально если LLM был временно недоступен — после восстановления используй
            <strong>Очередь → re-enqueue по фильтру reason=llm_unavailable</strong>.
            Если skipped с разными reasons — посмотри breakdown, чаще всего это <code>ml_no_match</code>
            (T3 LLM не нашёл совпадения) — это правильное поведение, оператор должен матчить вручную.
          </p>
        </Section>

        <Section id="glossary" title="Глоссарий">
          <dl className="space-y-2.5">
            <Glossary term="embedding">
              Числовой вектор (для bge-m3 — 1024 dimensions), представляющий текст
              в семантическом пространстве. Близкие по смыслу строки имеют близкие векторы.
            </Glossary>
            <Glossary term="cosine similarity">
              Метрика близости двух векторов: 1 = идентичные направления, 0 = ортогональные.
              Не зависит от длины вектора. Пороги: 0.85 = очень близко, 0.70 = неоднозначно.
            </Glossary>
            <Glossary term="pgvector / HNSW">
              Расширение Postgres для vector(N) типа + HNSW индекс для approximate nearest
              neighbor search. Параметры m=16, ef_construction=128 — стандарт для 1024-dim.
            </Glossary>
            <Glossary term="pg_trgm">
              Triграммный индекс Postgres для fuzzy-text-match по similarity. Хорош для
              опечаток, плохо для семантики. Используется в T1.
            </Glossary>
            <Glossary term="Circuit Breaker">
              Паттерн отказоустойчивости. После N подряд провалов внешнего сервиса (Ollama)
              цепь «открывается» — все запросы falling fast без реального вызова. Через
              recovery_timeout — пробная попытка (half-open). Защищает от каскадных сбоев.
            </Glossary>
            <Glossary term="half-open probe">
              Состояние Circuit Breaker между open и closed. После timeout первый реальный
              запрос проходит — если успешен, цепь закрывается; если нет, опять open.
            </Glossary>
            <Glossary term="match_queue / match_decisions / match_log">
              Три таблицы: <strong>queue</strong> — outbox (pending → processing → done),
              <strong>decisions</strong> — T0 cache (title_norm → game_id), <strong>log</strong>
              — аудит-журнал (immutable, с soft-revert через reverted_at).
            </Glossary>
            <Glossary term="auto_t1 / auto_t2 / auto_t3">
              Action в match_log: на каком tier было принято решение. <code>auto_t0</code>
              не пишется (cache hit — воркер не вызывал, ingest пропустил save_decision).
            </Glossary>
            <Glossary term="vec_below_threshold / vec_ambiguous">
              Reason для T2-результатов: <strong>below</strong> — один кандидат ниже auto-порога
              (не идёт в T3), <strong>ambiguous</strong> — ≥2 кандидата выше min_score (идёт в T3
              на арбитраж).
            </Glossary>
            <Glossary term="kill-switch / runtime_flags">
              Таблица с boolean-флагами (ml_enabled), хранится в Postgres. Frontend → PATCH
              {' /admin/runtime-flags/{key} '} → invalidate process-local cache (TTL ≤ 5с). Все
              инстансы catalog'а подхватят через TTL.
            </Glossary>
          </dl>
        </Section>

        <div className="mt-12 pt-6 border-t border-gray-800/60 text-[11px] text-gray-600">
          <p className="flex items-center gap-2">
            <AlertTriangle size={11} className="text-amber-500/60" />
            Эта вкладка — операционная справка, не исходник правды. Точная семантика —
            всегда в коде <code className="text-violet-300/80">services/catalog/catalog/matching/v2/</code>.
          </p>
        </div>
      </article>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={`mhelp-${id}`} className="scroll-mt-4 mb-10">
      <h2 className="group flex items-center gap-2 text-base font-semibold text-gray-100 mb-3 pb-2 border-b border-gray-800/60">
        <span>{title}</span>
        <a
          href={`#mhelp-${id}`}
          className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-violet-400 transition-opacity"
          aria-label={`Ссылка на «${title}»`}
        >
          <Link2 size={12} />
        </a>
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-gray-300 [&_code]:font-mono [&_code]:text-violet-300 [&_code]:text-[0.92em] [&_code]:bg-violet-950/30 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_ul]:list-disc [&_ul]:ml-5 [&_ul]:space-y-1.5 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:ml-5 [&_ol]:space-y-1.5 [&_ol]:my-2">
        {children}
      </div>
    </section>
  )
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] uppercase tracking-wider font-semibold text-gray-400 mt-4 mb-1">
      {children}
    </h3>
  )
}

function Glossary({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 items-baseline">
      <dt className="font-mono text-[11px] text-violet-300">{term}</dt>
      <dd className="text-xs text-gray-300 leading-relaxed">{children}</dd>
    </div>
  )
}

function PipelineDiagram() {
  // ASCII-style flow для оператора
  return (
    <pre className={clsx(
      'font-mono text-[10px] leading-relaxed text-gray-400',
      'bg-black/40 border border-gray-800/60 rounded p-3 overflow-x-auto',
      'my-3',
    )}>
{`  ingest /offers ──→ ┌──────────────┐ hit
                     │ T0  cache    │═════════════════╗
                     └──────┬───────┘                 ║
                            ▼ miss                    ║
                     ┌──────────────┐ ≥0.92           ║
                     │ T1  pg_trgm  │═════════════════╣
                     └──────┬───────┘                 ║
                            ▼ <0.92                   ║
                     ┌──────────────┐                 ║
                     │ match_queue  │  (outbox)       ║
                     └──────┬───────┘                 ║
                            │  worker tick (10s)      ║
                            ▼                         ║
                     ┌──────────────┐ ≥0.85 single    ║
                     │ T2  bge-m3   │═════════════════╣
                     │     cosine   │                 ║
                     └──────┬───────┘                 ║
                            ▼ ambiguous (≥2 ≥0.70)    ║
                     ┌──────────────┐ conf≥0.75       ║
                     │ T3  qwen LLM │═════════════════╣
                     └──────┬───────┘                 ║
                            ▼ low conf / no_match     ║
                     ┌──────────────┐                 ║
                     │ T4  manual   │  ←operator      ║
                     └──────────────┘                 ║
                                                      ▼
                                              offers.game_id
                                              match_log entry`}
    </pre>
  )
}
