import type { ReactNode } from 'react'
import { formatMoney } from '../utils/format'

export type IconName =
  | 'dashboard'
  | 'billing'
  | 'products'
  | 'invoices'
  | 'customers'
  | 'reports'
  | 'assistant'
  | 'search'
  | 'plus'
  | 'close'
  | 'edit'
  | 'delete'
  | 'download'
  | 'print'
  | 'menu'
  | 'calendar'
  | 'check'
  | 'arrow'
  | 'barcode'
  | 'cash'
  | 'upi'

const iconShapes: Record<IconName, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="13" y="3" width="8" height="5" rx="1.5" /><rect x="13" y="10" width="8" height="11" rx="1.5" /><rect x="3" y="13" width="8" height="8" rx="1.5" /></>,
  billing: <><path d="M5 3h14v18l-3.5-2-3.5 2-3.5-2L5 21z" /><path d="M8 8h8M8 12h8M8 16h4" /></>,
  products: <><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z" /><path d="m4.5 7.8 7.5 4.3 7.5-4.3M12 12v9" /></>,
  invoices: <><path d="M6 3h12v18l-3-1.8-3 1.8-3-1.8L6 21z" /><path d="M9 8h6M9 12h6M9 16h3" /></>,
  customers: <><circle cx="9" cy="8" r="3" /><path d="M3 20v-1a6 6 0 0 1 12 0v1zM16 5.5a3 3 0 0 1 0 5.8M18 14a5 5 0 0 1 3 4.5V20" /></>,
  reports: <><path d="M4 19V5M4 19h17" /><path d="m7 15 4-4 3 2 6-7" /></>,
  assistant: <><path d="M12 3a8 8 0 0 0-8 8v3a3 3 0 0 0 3 3h1v-6H7a5 5 0 0 1 10 0h-1v6h1a3 3 0 0 0 3-3v-3a8 8 0 0 0-8-8z" /><path d="M9 20h4" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  close: <><path d="m6 6 12 12M18 6 6 18" /></>,
  edit: <><path d="m4 16.5-.8 4.3 4.3-.8L19 8.5 15.5 5z" /><path d="m13.8 6.7 3.5 3.5" /></>,
  delete: <><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" /></>,
  download: <><path d="M12 3v12M7 10l5 5 5-5M4 21h16" /></>,
  print: <><path d="M7 8V3h10v5M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2" /><path d="M7 14h10v7H7z" /></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4M17 3v4M3 10h18" /></>,
  check: <><path d="m5 12 4 4L19 6" /></>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  barcode: <><path d="M4 5v14M8 5v14M11 5v14M15 5v14M18 5v14M21 5v14" /><path d="M2 5h1M2 19h1M21 5h1M21 19h1" /></>,
  cash: <><rect x="3" y="6" width="18" height="12" rx="2" /><circle cx="12" cy="12" r="3" /><path d="M6 9h.01M18 15h.01" /></>,
  upi: <><path d="M7 3h10v18H7z" /><path d="m10 13 2-4 2 4M10.8 12h2.4M11 18h2" /></>,
}

export function Icon({
  name,
  size = 18,
  className,
}: {
  name: IconName
  size?: number
  className?: string
}) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {iconShapes[name]}
    </svg>
  )
}

export function LoadingState({ label = 'Loading data…' }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorMessage({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="notice notice-error" role="alert">
      <span>{message}</span>
      {onRetry && <button className="text-button" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon"><Icon name="invoices" size={22} /></span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        aria-label={title}
        aria-modal="true"
        className={`modal${wide ? ' modal-wide' : ''}`}
        role="dialog"
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        {children}
      </section>
    </div>
  )
}

export function StatusPill({ children }: { children: ReactNode }) {
  return <span className="status-pill">{children}</span>
}

export function SalesChart({
  points,
}: {
  points: { date: string; revenue: string; invoice_count: number }[]
}) {
  if (points.length === 0) {
    return <div className="chart-empty">No sales data is available for this period.</div>
  }

  const values = points.map((point) => Number(point.revenue))
  const maximum = Math.max(...values, 1)
  const chartHeight = 170
  const barWidth = Math.min(34, 440 / points.length)
  const gap = points.length > 1 ? (480 - barWidth * points.length) / (points.length - 1) : 0

  return (
    <div className="chart-wrap">
      <svg
        aria-label="Revenue by day for the last seven days"
        className="sales-chart"
        role="img"
        viewBox="0 0 500 220"
      >
        {[0, 1, 2, 3].map((line) => {
          const y = 12 + line * (chartHeight / 3)
          return <line key={line} x1="8" x2="492" y1={y} y2={y} className="chart-gridline" />
        })}
        {points.map((point, index) => {
          const value = Number(point.revenue)
          const height = value > 0 ? Math.max(4, (value / maximum) * chartHeight) : 2
          const x = 10 + index * (barWidth + gap)
          const y = 182 - height
          const label = new Intl.DateTimeFormat('en-IN', { weekday: 'short' }).format(new Date(`${point.date}T12:00:00`))
          return (
            <g key={point.date}>
              <title>{`${point.date}: ${formatMoney(point.revenue)}, ${point.invoice_count} invoices`}</title>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={height}
                rx="6"
                className="chart-bar"
              />
              <text x={x + barWidth / 2} y="207" textAnchor="middle" className="chart-label">
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
