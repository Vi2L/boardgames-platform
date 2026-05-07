/**
 * BackupButton — pg_dump каталога одной кнопкой.
 *
 * Дёргает POST /api/catalog/backup (внутри — bin/backup-catalog.sh, который
 * через docker exec вызывает pg_dump в контейнере bg-postgres). Backup
 * файл хранится в .scratch/backups/ (gitignored), ротация на 10 файлов.
 *
 * UI:
 *   [Бэкап БД]  — главная кнопка (трогает БД, поэтому отдельная и заметная)
 *   [▾]         — попап со списком существующих backup'ов (только просмотр,
 *                 restore — намеренно из CLI, чтобы случайно не убить prod)
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Database, ChevronDown, Loader2 } from 'lucide-react'
import {
  createCatalogBackup,
  listCatalogBackups,
  type BackupFile,
} from '../../lib/catalog'

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function fmtAge(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} ч назад`
  const d = Math.floor(h / 24)
  return `${d} дн назад`
}

export function BackupButton() {
  const [showList, setShowList] = useState(false)
  const queryClient = useQueryClient()

  const backup = useMutation({
    mutationFn: createCatalogBackup,
    onSuccess: (r) => {
      toast.success(`Backup создан: ${r.file.name} (${fmtSize(r.file.size_bytes)})`)
      queryClient.invalidateQueries({ queryKey: ['catalog', 'backups'] })
    },
    onError: (e) => toast.error(`Не удалось сделать backup: ${e}`),
  })

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => backup.mutate()}
        disabled={backup.isPending}
        title="pg_dump catalog'а в .scratch/backups/"
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-amber-700 hover:bg-amber-600 disabled:opacity-40 text-white rounded-l border-r border-amber-900/40"
      >
        {backup.isPending
          ? <Loader2 size={12} className="animate-spin" />
          : <Database size={12} />}
        {backup.isPending ? 'Создаю…' : 'Бэкап БД'}
      </button>
      <button
        type="button"
        onClick={() => setShowList(v => !v)}
        title="Показать существующие backup'ы"
        className="px-2 py-1.5 text-xs bg-amber-700 hover:bg-amber-600 text-white rounded-r"
      >
        <ChevronDown size={12} />
      </button>
      {showList && <BackupList onClose={() => setShowList(false)} />}
    </div>
  )
}

function BackupList({ onClose }: { onClose: () => void }) {
  const list = useQuery({
    queryKey: ['catalog', 'backups'],
    queryFn: listCatalogBackups,
  })

  return (
    <>
      {/* overlay для закрытия по клику; см. подводный камень в CLAUDE.md
          о popover'ах — fixed inset-0 не вкладываем в overflow-hidden */}
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute right-0 top-full mt-1 z-50 w-96 max-h-96 overflow-y-auto bg-gray-900 border border-gray-700 rounded shadow-xl text-xs">
        <div className="px-3 py-2 border-b border-gray-800 text-gray-400 sticky top-0 bg-gray-900">
          Существующие backup'ы (новые сверху)
          {list.data && <span className="ml-2 text-gray-600">— {list.data.items.length}</span>}
        </div>
        {list.isLoading && <div className="px-3 py-3 text-gray-500">загрузка…</div>}
        {list.isError && <div className="px-3 py-3 text-red-400">ошибка: {String(list.error)}</div>}
        {list.data?.items.length === 0 && (
          <div className="px-3 py-3 text-gray-500">
            пусто — нажмите «Бэкап БД» чтобы создать первый
          </div>
        )}
        <div className="divide-y divide-gray-800">
          {list.data?.items.map(b => <BackupRow key={b.name} b={b} />)}
        </div>
        {list.data && (
          <div className="px-3 py-2 border-t border-gray-800 text-gray-600 text-[10px] sticky bottom-0 bg-gray-900">
            <span className="font-mono">{list.data.dir}</span>
            <div className="mt-1">restore — только из CLI: <span className="font-mono">bin/backup-catalog.sh --restore latest</span></div>
          </div>
        )}
      </div>
    </>
  )
}

function BackupRow({ b }: { b: BackupFile }) {
  return (
    <div className="px-3 py-2 hover:bg-gray-800/50 flex items-center gap-2">
      <div className="flex-1 min-w-0">
        <div className="font-mono text-gray-200 truncate">{b.name}</div>
        <div className="text-gray-500 text-[10px]">
          {fmtAge(b.modified_at)} · {new Date(b.modified_at).toLocaleString('ru-RU')}
        </div>
      </div>
      <div className="text-gray-400 flex-shrink-0">{fmtSize(b.size_bytes)}</div>
    </div>
  )
}
