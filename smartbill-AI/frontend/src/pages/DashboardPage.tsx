import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState, SalesChart } from '../components/Common'
import type { DashboardData } from '../types'
import type { PageKey } from '../App'
import { formatDate, formatMoney } from '../utils/format'

export function DashboardPage({
  refreshToken,
  onNavigate,
}: {
  refreshToken: number
  onNavigate: (page: PageKey) => void
}) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)

  const load = useCallback(async () => {
    try {
      const result = await apiRequest<DashboardData>('/reports/dashboard')
      setData(result)
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dashboard could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load, refreshToken, retryToken])

  if (loading && !data) return <LoadingState label="Loading your shop overview…" />
  if (error && !data) return <ErrorMessage message={error} onRetry={() => { setLoading(true); setError(null); setRetryToken((v) => v + 1) }} />
  if (!data) return null

  const cards = [
    { label: "Today's revenue", value: formatMoney(data.today_revenue), note: 'Excludes GST', icon: 'billing' as const, tone: 'mint' },
    { label: 'Total invoices', value: data.total_invoices.toLocaleString('en-IN'), note: `${data.today_invoice_count} today`, icon: 'invoices' as const, tone: 'blue' },
    { label: 'This month', value: formatMoney(data.monthly_revenue), note: 'Revenue excluding GST', icon: 'reports' as const, tone: 'violet' },
    { label: 'Customers', value: data.total_customers.toLocaleString('en-IN'), note: 'Customer profiles', icon: 'customers' as const, tone: 'amber' },
  ]

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div>
          <h1>Good day, shop owner <span className="wave">✦</span></h1>
          <p>Here’s how your store is doing. All figures come from your SmartBill records.</p>
        </div>
        <button className="button button-primary" onClick={() => onNavigate('billing')}>
          <Icon name="plus" /> Create a bill
        </button>
      </section>

      {error && <ErrorMessage message={error} onRetry={() => { setLoading(true); setError(null); setRetryToken((v) => v + 1) }} />}

      <section className="stats-grid" aria-label="Shop summary">
        {cards.map((card) => (
          <article className="stat-card" key={card.label}>
            <div className="stat-card-top">
              <span className="stat-label">{card.label}</span>
              <span className={`stat-icon stat-icon-${card.tone}`}><Icon name={card.icon} /></span>
            </div>
            <strong className="stat-value">{card.value}</strong>
            <span className="stat-note">{card.note}</span>
          </article>
        ))}
      </section>

      <section className="dashboard-grid">
        <article className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <h2>Sales overview</h2>
              <p>Net revenue over the last seven days</p>
            </div>
            <span className="panel-range"><span className="legend-dot" /> Revenue</span>
          </div>
          <SalesChart points={data.sales_overview} />
        </article>

        <article className="panel revenue-note-panel">
          <span className="note-icon"><Icon name="reports" size={20} /></span>
          <div>
            <h2>Revenue, not profit</h2>
            <p>{data.profit_note}</p>
          </div>
          <div className="revenue-note-value">
            <span>Revenue today</span>
            <strong>{formatMoney(data.today_revenue)}</strong>
          </div>
        </article>
      </section>

      <section className="panel transactions-panel">
        <div className="panel-heading">
          <div>
            <h2>Recent transactions</h2>
            <p>Your latest completed invoices</p>
          </div>
          <button className="button button-quiet" onClick={() => onNavigate('invoices')}>
            View invoices <Icon name="arrow" size={16} />
          </button>
        </div>
        {data.recent_invoices.length === 0 ? (
          <EmptyState
            title="No transactions yet"
            description="Completed bills will appear here as soon as you make your first sale."
            action={<button className="button button-primary" onClick={() => onNavigate('billing')}>Create first bill</button>}
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Invoice</th><th>Customer</th><th>Date</th><th>Payment</th><th className="align-right">Amount</th></tr>
              </thead>
              <tbody>
                {data.recent_invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td><span className="invoice-cell"><span className="table-leading-icon"><Icon name="invoices" size={16} /></span><strong>{invoice.invoice_number}</strong></span></td>
                    <td>{invoice.customer_name || 'Walk-in customer'}</td>
                    <td className="muted-cell">{formatDate(invoice.created_at)}</td>
                    <td><span className="payment-method">{invoice.payments[0]?.payment_method.toUpperCase() || '—'}</span></td>
                    <td className="align-right amount-cell">{formatMoney(invoice.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {loading && data && <div className="refresh-indicator"><span className="spinner spinner-small" /> Refreshing sales data…</div>}
    </div>
  )
}
