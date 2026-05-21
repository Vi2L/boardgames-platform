/**
 * /__design — галерея ui-примитивов.
 *
 * Доступна только при `import.meta.env.DEV` (см. App.tsx). Используется как:
 *   1. Smoke-тест: после изменений в ui/* открываем страницу, видим что всё
 *      рендерится без ошибок (PR 1 acceptance: «галерея всех компонентов»).
 *   2. Самодокументация: новый разработчик открывает один URL вместо чтения
 *      components.md + поиска usage по проекту.
 *
 * Layout: вертикальная лента секций. Каждый компонент — `<Section>` с
 * заголовком и live-примером во всех variant'ах × size'ах.
 *
 * Без поиска / фильтрации — это не Storybook. Все секции на одной странице,
 * сжато (1280×800 → ~3 экрана).
 */
import { useState, type ReactNode } from 'react'
import {
  Search, Link as LinkIcon, Ban, Sparkles, Plus, Filter, Check,
  X, AlertTriangle, Activity, Database, Settings,
} from 'lucide-react'

import {
  Button, IconButton, Input, Textarea, Select, Combobox,
  Badge, StatusDot, Tag, ProgressBar, Skeleton, KBD,
  EmptyState, Dialog, Drawer, Tooltip, Tabs, Toolbar,
  DataTable, JobLogPanel, HealthCard, Popover,
} from '../../components/ui'
import { HelpBox } from '../../components/shared/HelpBox'

export function DesignSystemPage() {
  return (
    <div className="max-w-5xl mx-auto py-6 px-6 space-y-8">
      <header className="border-b border-zinc-800 pb-4">
        <h1 className="text-xl font-semibold text-zinc-100">/__design · UI Gallery</h1>
        <p className="text-xs text-zinc-500 mt-1">
          Living-доска компонентов из <code className="font-mono text-indigo-300">src/components/ui</code>.
          Доступна только в dev-сборке. Смотри спеку в{' '}
          <code className="font-mono text-indigo-300">.scratch/admin-panel-design/.../components.md</code>.
        </p>
      </header>

      <Section title="Button">
        <Row label="Variants">
          <Button variant="primary" icon={LinkIcon}>Primary</Button>
          <Button variant="secondary" icon={Filter}>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger" icon={Ban}>Danger</Button>
          <Button variant="success" icon={Check}>Success</Button>
          <Button variant="warn" icon={AlertTriangle}>Warn</Button>
        </Row>
        <Row label="Sizes">
          <Button size="xs" icon={Plus}>xs (24)</Button>
          <Button size="sm" icon={Plus}>sm (28)</Button>
          <Button size="md" icon={Plus}>md (32)</Button>
        </Row>
        <Row label="States">
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
          <Button iconRight={Sparkles}>iconRight</Button>
        </Row>
      </Section>

      <Section title="IconButton">
        <Row label="Variants">
          <IconButton icon={LinkIcon} variant="primary" aria-label="link" />
          <IconButton icon={Filter} variant="secondary" aria-label="filter" />
          <IconButton icon={X} variant="ghost" aria-label="close" />
          <IconButton icon={Ban} variant="danger" aria-label="reject" />
        </Row>
        <Row label="Sizes">
          <IconButton icon={Plus} size="xs" aria-label="add" />
          <IconButton icon={Plus} size="sm" aria-label="add" />
          <IconButton icon={Plus} size="md" aria-label="add" />
        </Row>
      </Section>

      <Section title="Input · Textarea">
        <Row label="Input">
          <div className="w-64"><Input icon={Search} placeholder="поиск…" /></div>
          <div className="w-32"><Input mono placeholder="ID" /></div>
          <div className="w-32"><Input error placeholder="error" /></div>
        </Row>
        <Row label="Textarea">
          <div className="w-96"><Textarea placeholder="комментарий" /></div>
        </Row>
      </Section>

      <Section title="Select · Combobox">
        <SelectComboDemo />
      </Section>

      <Section title="Badge · StatusDot · Tag">
        <Row label="Pipeline">
          <Badge status="pending" />
          <Badge status="processing" />
          <Badge status="done" />
          <Badge status="failed" />
          <Badge status="skipped" />
        </Row>
        <Row label="Matching">
          <Badge status="auto" />
          <Badge status="manual" />
          <Badge status="unmatched" />
          <Badge status="rejected" />
        </Row>
        <Row label="Circuit Breaker">
          <Badge status="closed" />
          <Badge status="half_open" />
          <Badge status="open" />
          <Badge status="unknown" />
        </Row>
        <Row label="StatusDot animated">
          <StatusDot status="processing" animated />
          <StatusDot status="half_open" animated />
          <StatusDot status="open" />
          <StatusDot status="closed" />
        </Row>
        <Row label="Tag">
          <Tag tone="info">manual</Tag>
          <Tag tone="ok">RU localized</Tag>
          <Tag tone="neutral" mono>bgg_id=12345</Tag>
        </Row>
      </Section>

      <Section title="ProgressBar">
        <Row label="Variants">
          <div className="w-64"><ProgressBar value={42} tone="info" withLabel /></div>
          <div className="w-64"><ProgressBar value={100} tone="ok" withLabel /></div>
          <div className="w-64"><ProgressBar value={70} tone="warn" withLabel /></div>
          <div className="w-64"><ProgressBar value={0} indeterminate tone="info" /></div>
        </Row>
      </Section>

      <Section title="Skeleton">
        <Row label="Single">
          <Skeleton className="w-32 h-3" />
          <Skeleton className="w-48 h-3" />
        </Row>
        <Row label="Row (compact)">
          <div className="w-full max-w-2xl border border-zinc-800 rounded">
            <Skeleton.Row columns={5} />
            <Skeleton.Row columns={5} />
            <Skeleton.Row columns={5} />
          </div>
        </Row>
      </Section>

      <Section title="KBD">
        <Row label="Shortcut">
          <span className="text-xs text-zinc-400">
            Открыть палитру: <KBD>⌘</KBD> <KBD>K</KBD>
          </span>
          <span className="text-xs text-zinc-400">
            Связать: <KBD>L</KBD>
          </span>
        </Row>
      </Section>

      <Section title="Tooltip">
        <Row label="Position">
          <Tooltip content="Топ tooltip"><Button variant="ghost">hover top</Button></Tooltip>
          <Tooltip content={<>Шорткат · <KBD>L</KBD></>}><IconButton icon={LinkIcon} aria-label="link" /></Tooltip>
        </Row>
      </Section>

      <Section title="Popover · HelpBox (WT-F13)">
        <Row label="Popover (низкоуровневый)">
          <Popover content={<div className="text-xs text-zinc-200">Произвольный JSX в popover'е. Закрывается по клику вне / Esc.</div>}>
            <Button variant="ghost">click to open</Button>
          </Popover>
        </Row>
        <Row label="HelpBox — иконка">
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-300">
            T1 порог <HelpBox topic="matching.tier_t1" />
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-300">
            bucket good <HelpBox topic="catalog.bucket_good" />
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-300">
            DLQ <HelpBox topic="dlq.what_is_dlq" />
          </span>
        </Row>
        <Row label="HelpBox с label">
          <HelpBox topic="matching.tier_t2" label="T2" />
          <HelpBox topic="matching.tier_t3" label="T3" />
        </Row>
        <Row label="Стороны">
          <HelpBox topic="matching.skipped_reasons" side="top" />
          <HelpBox topic="matching.skipped_reasons" side="right" />
          <HelpBox topic="matching.skipped_reasons" side="bottom" />
          <HelpBox topic="matching.skipped_reasons" side="left" />
        </Row>
        <p className="text-[11px] text-zinc-500 mt-2">
          Палитра + чек-лист добавления нового топика — в{' '}
          <code className="font-mono text-indigo-300">frontend/CLAUDE.md</code>{' '}
          секция «Help-контент».
        </p>
      </Section>

      <Section title="EmptyState">
        <div className="border border-zinc-800 rounded">
          <EmptyState
            icon={Search}
            title="Очередь пуста"
            description="Все офферы из последнего пересчёта обработаны."
            action={<Button icon={Sparkles}>Reassess всё</Button>}
          />
        </div>
      </Section>

      <Section title="Tabs">
        <TabsDemo />
      </Section>

      <Section title="Dialog · Drawer">
        <OverlaysDemo />
      </Section>

      <Section title="Toolbar (bulk-actions)">
        <ToolbarDemo />
      </Section>

      <Section title="DataTable">
        <DataTableDemo />
      </Section>

      <Section title="JobLogPanel">
        <JobLogDemo />
      </Section>

      <Section title="HealthCard">
        <Row label="Variants">
          <HealthCard
            name="bge-m3"
            sub="embed model"
            status="closed"
            details={[
              { label: 'failures', value: '0' },
              { label: 'uptime', value: '4ч 12м' },
              { label: 'last check', value: '23с назад' },
            ]}
            sparkline={[0.2, 0.3, 0.5, 0.4, 0.7, 0.6, 0.8, 0.9, 0.85, 0.95]}
          />
          <HealthCard
            name="qwen2.5"
            sub="llm arbiter"
            status="half_open"
            details={['probe через ~30с', 'failures: 2', 'last fail 45с назад']}
          />
          <HealthCard
            name="parsers"
            sub="6 stores"
            status="open"
            details={['Avito 503', 'WB 429', 'last success 2м']}
          />
        </Row>
      </Section>

      <footer className="text-xxs text-zinc-600 pt-6 border-t border-zinc-800">
        Источник правды: <code className="font-mono">src/components/ui/index.ts</code> ·{' '}
        <code className="font-mono">src/lib/design-tokens.ts</code>
      </footer>
    </div>
  )
}

// ─── Internal helpers ───────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs uppercase tracking-widest text-zinc-500 font-mono">{title}</h2>
      <div className="space-y-2 p-4 bg-zinc-900/40 border border-zinc-800 rounded">
        {children}
      </div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xxs uppercase tracking-widest text-zinc-600 font-mono w-20 shrink-0">
        {label}
      </span>
      {children}
    </div>
  )
}

// ─── Interactive demos ──────────────────────────────────────────────────────

function SelectComboDemo() {
  const [v1, setV1] = useState<string>('')
  const [v2, setV2] = useState<string>('')
  const opts = [
    { value: 'hg', label: 'HobbyGames', hint: '142' },
    { value: 'lavka', label: 'Лавка игр', hint: '38' },
    { value: 'gaga', label: 'GaGa', hint: '12' },
    { value: 'avito', label: 'Авито', hint: '203' },
    { value: 'wb', label: 'Wildberries', hint: '67' },
  ]
  return (
    <>
      <Row label="Select">
        <div className="w-48">
          <Select value={v1} onValueChange={setV1} options={opts} placeholder="store" />
        </div>
      </Row>
      <Row label="Combobox">
        <div className="w-48">
          <Combobox value={v2} onChange={setV2} options={opts} placeholder="найти игру…" searchPlaceholder="фильтр…" />
        </div>
      </Row>
    </>
  )
}

function TabsDemo() {
  const [t, setT] = useState('queue')
  return (
    <Tabs value={t} onValueChange={setT}>
      <Tabs.List>
        <Tabs.Trigger value="queue">Очередь <span className="ml-1 text-xxs font-mono text-zinc-500 tabular-nums">142</span></Tabs.Trigger>
        <Tabs.Trigger value="log">Журнал <span className="ml-1 text-xxs font-mono text-zinc-500 tabular-nums">2.1k</span></Tabs.Trigger>
        <Tabs.Trigger value="settings">Settings</Tabs.Trigger>
        <Tabs.Trigger value="dis" disabled>Disabled</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="queue" className="py-2 text-xs text-zinc-400">Очередь — контент</Tabs.Content>
      <Tabs.Content value="log" className="py-2 text-xs text-zinc-400">Журнал — контент</Tabs.Content>
      <Tabs.Content value="settings" className="py-2 text-xs text-zinc-400">Settings — контент</Tabs.Content>
    </Tabs>
  )
}

function OverlaysDemo() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  return (
    <>
      <Row label="Triggers">
        <Button onClick={() => setDialogOpen(true)}>Открыть Dialog</Button>
        <Button onClick={() => setDrawerOpen(true)}>Открыть Drawer</Button>
      </Row>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <Dialog.Content
          title="Подтвердить bulk-action"
          description="Будет применено к 23 выбранным офферам. Операция логируется в match_log с общим batch_id (revert возможен)."
        >
          <p className="text-xs text-zinc-400">Состояние: <Badge status="processing" /> · Score: <span className="font-mono tabular-nums text-emerald-400">0.87</span></p>
          <Dialog.Actions>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>Отмена</Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>OK</Button>
          </Dialog.Actions>
        </Dialog.Content>
      </Dialog>
      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen}>
        <Drawer.Content width={440}>
          <Drawer.Header>
            <div className="flex-1 min-w-0">
              <Drawer.Title>Offer #1247</Drawer.Title>
              <Drawer.Description>HobbyGames · 169,500 ₽</Drawer.Description>
            </div>
            <Drawer.Nav onPrev={() => null} onNext={() => null} />
            <Drawer.Close />
          </Drawer.Header>
          <Drawer.Body>
            <div className="space-y-3 text-xs text-zinc-300">
              <p>Демо drawer-контент. Слева таблица остаётся кликабельной — это split-view, не модал.</p>
              <p>Состояние: <Badge status="auto" /> Score: <span className="font-mono tabular-nums text-emerald-400">0.92</span></p>
            </div>
          </Drawer.Body>
          <Drawer.Footer>
            <Button variant="ghost" onClick={() => setDrawerOpen(false)}>Закрыть</Button>
            <div className="flex-1" />
            <Button variant="danger" icon={Ban}>Отклонить</Button>
            <Button variant="primary" icon={LinkIcon}>Связать</Button>
          </Drawer.Footer>
        </Drawer.Content>
      </Drawer>
    </>
  )
}

function ToolbarDemo() {
  const [selected, setSelected] = useState(new Set<number>())
  const toggle = (id: number) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }
  return (
    <div className="space-y-2">
      <Row label="Select">
        {[1, 2, 3].map(i => (
          <label key={i} className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer">
            <input type="checkbox" checked={selected.has(i)} onChange={() => toggle(i)} />
            row {i}
          </label>
        ))}
      </Row>
      <Toolbar visible={selected.size > 0}>
        <span>{selected.size} выбрано</span>
        <button
          onClick={() => setSelected(new Set())}
          className="text-zinc-500 hover:text-zinc-300"
        >
          Снять
        </button>
        <Toolbar.Spacer />
        <Button variant="danger" icon={Ban}>Отклонить</Button>
        <Button variant="primary" icon={LinkIcon}>Связать</Button>
      </Toolbar>
    </div>
  )
}

function DataTableDemo() {
  const data = Array.from({ length: 20 }).map((_, i) => ({
    id: i + 1,
    store: ['hg', 'lavka', 'gaga', 'avito'][i % 4],
    title: `Sample game title #${i + 1} — ${'lorem ipsum '.repeat(i % 3 + 1)}`,
    score: Math.random(),
    status: (['auto', 'manual', 'unmatched', 'rejected'] as const)[i % 4],
  }))
  return (
    <div className="border border-zinc-800 rounded h-64">
      <DataTable
        data={data}
        rowKey={(r) => r.id}
        columns={[
          { accessorKey: 'id', header: 'id', cell: (c) => <span className="font-mono text-zinc-500">#{c.getValue() as number}</span>, size: 60 },
          { accessorKey: 'store', header: 'store', cell: (c) => <span className="font-mono text-zinc-500">{c.getValue() as string}</span>, size: 80 },
          { accessorKey: 'title', header: 'title', cell: (c) => <span className="truncate">{c.getValue() as string}</span> },
          { accessorKey: 'score', header: 'score', cell: (c) => {
            const v = c.getValue() as number
            const color = v >= 0.6 ? 'text-emerald-400' : v >= 0.3 ? 'text-amber-400' : 'text-zinc-500'
            return <span className={`font-mono tabular-nums ${color}`}>{v.toFixed(3)}</span>
          }, size: 80 },
          { accessorKey: 'status', header: 'status', cell: (c) => <Badge status={c.getValue() as 'auto'} />, size: 100 },
        ]}
      />
    </div>
  )
}

function JobLogDemo() {
  const lines = [
    '[2026-05-16 10:42:01] INFO   bgg-batch | starting · rank_le=1000',
    '[2026-05-16 10:42:03] OK     bgg-batch | fetched 20/1000 (2.0%)',
    '[2026-05-16 10:42:05] OK     bgg-batch | fetched 40/1000 (4.0%)',
    '[2026-05-16 10:42:07] WARN   bgg-batch | rate-limited, backoff 3s',
    '[2026-05-16 10:42:10] OK     bgg-batch | fetched 60/1000 (6.0%)',
    '[2026-05-16 10:42:14] FAIL   bgg-batch | thing/12345: 5xx, will retry',
    '[2026-05-16 10:42:17] OK     bgg-batch | fetched 80/1000 (8.0%)',
    '[2026-05-16 10:42:19] SKIP   bgg-batch | thing/12345: still uptodate',
  ]
  return <JobLogPanel lines={lines} height="h-48" />
}

void Activity; void Database; void Settings  // satisfy unused-import lint
