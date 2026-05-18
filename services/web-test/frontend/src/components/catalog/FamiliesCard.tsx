/**
 * FamiliesCard (CAT-8) — блок «BGG-серии и связанные игры» в карточке Game.
 *
 * Источник — `GameDetailOut.families[]`: каждая семья содержит meta + `member_count`
 * (включая отсутствующие в catalog) + `members[]` (только присутствующие).
 *
 * Дизайн: компактный список серий с числом членов; членов разворачиваем в ряд
 * тэгов-ссылок. Кликабельные ведут на `/catalog/games/{game_id}` (или открывают
 * drawer этой игры — пока reuse'им window.location/anchor, без программной
 * навигации в drawer parent, чтобы не вносить координацию state'ов).
 */
import type { BggFamily, BggFamilyMember } from '../../lib/catalog'
import { Users } from 'lucide-react'
import { Link } from 'react-router-dom'

export function FamiliesCard({ families }: { families: BggFamily[] }) {
  if (!families.length) {
    return (
      <div className="text-xs text-gray-500 italic py-2">
        Игра не связана с BGG-семьями. Cascade-import (`enrich_one`) или scheduler
        job `bgg_family_refresh` подтянут связи при следующем обогащении.
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {families.map(f => <FamilyBlock key={f.bgg_family_id} family={f} />)}
    </div>
  )
}

function FamilyBlock({ family }: { family: BggFamily }) {
  const known = family.members
  const unknown = Math.max(0, family.member_count - known.length)
  return (
    <div className="border border-gray-800 bg-gray-900/40 rounded p-2.5">
      <div className="flex items-center gap-2 mb-1.5">
        <Users size={12} className="text-indigo-400" />
        <span className="text-xs font-semibold text-gray-200">{family.name}</span>
        <span className="text-[10px] text-gray-500">
          ({family.member_count} {plural(family.member_count, 'игра', 'игры', 'игр')}
          {unknown > 0 && `, ${unknown} ещё не в catalog`})
        </span>
      </div>
      {family.description && (
        <p className="text-[11px] text-gray-400 mb-2 leading-relaxed line-clamp-2">
          {family.description}
        </p>
      )}
      {known.length === 0 ? (
        <div className="text-[11px] text-gray-500 italic">
          Члены этой серии пока не обогащены. Cascade подтянет их в фоне.
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {known.map(m => <MemberTag key={m.bgg_id} member={m} />)}
        </div>
      )}
    </div>
  )
}

function MemberTag({ member }: { member: BggFamilyMember }) {
  // game_id всегда есть у known-членов (по фильтру в API), но TS не знает.
  if (member.game_id == null) return null
  // SPA-навигация через react-router-dom — без перезагрузки страницы, что
  // сохраняет state TanStack Query и Zustand. <a href> сбросил бы весь app-state.
  return (
    <Link
      to={`/catalog/games/${member.game_id}`}
      className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-gray-100"
      title={`bgg_id=${member.bgg_id}${member.year ? ` (${member.year})` : ''}`}
    >
      <span className="truncate max-w-[200px]">{member.title ?? `bgg-${member.bgg_id}`}</span>
      {member.year != null && (
        <span className="text-[10px] text-gray-500">({member.year})</span>
      )}
    </Link>
  )
}

// Простая склонялка под русскую плюрализацию — без i18n-пакета, 3 формы.
function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}
