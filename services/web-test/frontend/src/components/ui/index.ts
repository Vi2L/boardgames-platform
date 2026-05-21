/**
 * Barrel-экспорт всех ui-примитивов.
 *
 * Конвенция: импорт от `'../../components/ui'` или `'@/components/ui'` —
 * чище страничного кода. Каждый компонент — один файл с named export.
 *
 * См. components.md для контрактов.
 */

// ─── Form & action ─────────────────────────────────────────────────────────
export { Button, type ButtonProps } from './Button'
export { IconButton, type IconButtonProps } from './IconButton'
export { Input, type InputProps } from './Input'
export { Textarea, type TextareaProps } from './Textarea'
export { Select, type SelectProps, type SelectOption } from './Select'
export { Combobox, type ComboboxProps, type ComboboxOption } from './Combobox'

// ─── Status / display ──────────────────────────────────────────────────────
export { Badge, type BadgeProps } from './Badge'
export { StatusDot, type StatusDotProps } from './StatusDot'
export { Tag, type TagProps } from './Tag'
export { ProgressBar, type ProgressBarProps } from './ProgressBar'
export { Skeleton } from './Skeleton'
export { KBD } from './KBD'
export { EmptyState, type EmptyStateProps } from './EmptyState'

// ─── Overlays ──────────────────────────────────────────────────────────────
export { Dialog, type DialogProps } from './Dialog'
export { Drawer, type DrawerProps } from './Drawer'
export { Tooltip, TooltipProvider, type TooltipProps } from './Tooltip'
export { Popover, type PopoverProps } from './Popover'

// ─── Navigation / containers ───────────────────────────────────────────────
export { Tabs, type TabsProps } from './Tabs'
export { Toolbar, type ToolbarProps } from './Toolbar'

// ─── Composite ─────────────────────────────────────────────────────────────
export { DataTable, type DataTableProps } from './DataTable'
export { JobLogPanel, type JobLogPanelProps } from './JobLogPanel'
export { HealthCard, type HealthCardProps } from './HealthCard'
export {
  CommandPalette, useCommand,
  type AppCommand, type NavCommandItem,
} from './CommandPalette'
