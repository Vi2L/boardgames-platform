import { useEffect, useMemo, useState } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import {
  Search, Database, FlaskConical, Library, Bug, Inbox, Boxes,
  Activity, RefreshCw, Sparkles, BookOpen,
} from 'lucide-react'

import { SearchPage } from './pages/SearchPage'
import { DatabasePage } from './pages/DatabasePage'
import { ProductPage } from './pages/ProductPage'
import { TestingPage } from './pages/TestingPage'
import { CatalogPage } from './pages/CatalogPage'
import { DebugPage } from './pages/DebugPage'
import { DlqPage } from './pages/DlqPage'
import { SourcesPage } from './pages/SourcesPage'
import { StatusPage } from './pages/StatusPage'
import { BggSyncPage } from './pages/BggSyncPage'
import { MatchingPage } from './pages/MatchingPage'
import { DiffView } from './components/testing/DiffView'

import { AppShell } from './components/layout/AppShell'
import type { NavItem } from './components/layout/Sidebar'
import { CommandPalette } from './components/ui/CommandPalette'
import { HealthBadge } from './components/shared/HealthBadge'

// Lazy-import DesignSystemPage только в DEV. Через dynamic-import — Vite
// дропнет страницу из prod-bundle (tree-shake по DEV-guard'у).
import { DesignSystemPage } from './pages/__design/DesignSystemPage'

// ─── NAV (плоский список, ТЗ §10) ───────────────────────────────────────────

const NAV: NavItem[] = [
  { to: '/',          label: 'Поиск',     icon: Search },
  // WT-F9: «Парсеры» удалена из сайдбара. Функции дублировались с
  // /debug (Live Test + Invalidate cache) и /sources/{provider}.
  // /parsers route оставлен с Navigate'ом ещё на 2-3 недели для
  // закладок — удалить после 2026-06-10.
  { to: '/debug',     label: 'Debug',     icon: Bug },
  { to: '/database',  label: 'БД',        icon: Database },
  { to: '/catalog',   label: 'Каталог',   icon: Library },
  { to: '/matching',  label: 'Матчинг',   icon: Sparkles },
  { to: '/bgg-sync',  label: 'BGG Sync',  icon: RefreshCw },
  { to: '/sources',   label: 'Источники', icon: Boxes },
  { to: '/testing',   label: 'Тесты',     icon: FlaskConical },
  { to: '/dlq',       label: 'DLQ',       icon: Inbox },
  { to: '/status',    label: 'Статус',    icon: Activity },
  // external=true → открывается в новой вкладке как статический /help.html,
  // лежит в frontend/public/. Не часть SPA.
  { to: '/help.html', label: 'Помощь',    icon: BookOpen, external: true },
]

// ─── Breadcrumb mapping ─────────────────────────────────────────────────────
// MVP: один-два уровня по path. Полная схема — в `src/lib/breadcrumbs.ts`,
// пока inline.
function deriveBreadcrumbs(pathname: string): { label: string; href?: string }[] {
  const item = NAV.find(n => n.to !== '/' && pathname.startsWith(n.to))
  if (!item) {
    if (pathname === '/') return [{ label: 'Поиск' }]
    if (pathname.startsWith('/products/')) return [{ label: 'Продукт' }]
    if (pathname === '/__design') return [{ label: '__design' }]
    return []
  }
  return [{ label: item.label }]
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [paletteOpen, setPaletteOpen] = useState(false)

  // Глобальный Cmd+/ → фокус инпута поиска. (Cmd+K палитру слушает сама
  // CommandPalette изнутри — не дублируем.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '/') {
        e.preventDefault()
        const focus = () => {
          const el = document.getElementById('search-q-input') as HTMLInputElement | null
          el?.focus()
          el?.select()
        }
        if (window.location.pathname !== '/') {
          navigate('/')
          setTimeout(focus, 50)
        } else {
          focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navigate])

  const breadcrumbs = useMemo(
    () => deriveBreadcrumbs(location.pathname),
    [location.pathname],
  )

  return (
    <>
      <AppShell
        navItems={NAV}
        breadcrumbs={breadcrumbs}
        onOpenCommandPalette={() => setPaletteOpen(true)}
        bgJobsCount={0 /* TODO: useBgJobs() — PR 3+ */}
        sidebarFooter={
          // HealthBadge cluster — пока переиспользуем существующий компонент.
          // В будущем он переедет на новые tokens и станет частью ui/.
          <HealthBadge />
        }
      >
        <Routes>
          <Route path="/" element={<SearchPage />} />
          {/* WT-F9: redirect для старых закладок. Удалить после 2026-06-10
              (даём 2-3 недели) — тогда же удалить ParsersPage.tsx. */}
          <Route path="/parsers" element={<Navigate to="/debug" replace />} />
          <Route path="/debug" element={<DebugPage />} />
          <Route path="/dlq" element={<DlqPage />} />
          <Route path="/database" element={<DatabasePage />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/matching" element={<MatchingPage />} />
          <Route path="/bgg-sync" element={<BggSyncPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/sources/:provider" element={<SourcesPage />} />
          <Route path="/products/:id" element={<ProductPage />} />
          <Route path="/testing" element={<TestingPage />} />
          <Route path="/testing/diff" element={<DiffView />} />
          <Route path="/status" element={<StatusPage />} />
          {/* /__design — только в dev-сборке. В prod роут существует но
              рендерит EmptyState (или ничего); чтобы вообще убрать из
              бандла — нужно сделать lazy() + import.meta.env.DEV guard,
              пока упрощаем. */}
          {import.meta.env.DEV && (
            <Route path="/__design" element={<DesignSystemPage />} />
          )}
        </Routes>
      </AppShell>

      {/* Глобальная Cmd+K палитра — слушает hotkey изнутри */}
      <CommandPalette navItems={NAV} />
      {/*
        `paletteOpen`-state используется для programmatic-open (например, из
        Topbar-кнопки). Сам компонент CommandPalette управляет своим open
        через global hotkey — наш state синхронизировать не обязательно.
        TODO: вынести open-state наружу через хук useCommandPaletteOpen().
      */}
      {void paletteOpen}
    </>
  )
}
