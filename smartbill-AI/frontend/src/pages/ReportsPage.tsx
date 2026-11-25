import { useState, type FormEvent } from 'react'
import { apiRequest } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState } from '../components/Common'
import type { SalesReport } from '../types'
import { formatMoney } from '../utils/format'

type ReportPeriod = 'daily' | 'weekly' | 'monthly' | 'custom'

function todayString() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function ReportsPage() {
  const [period, setPeriod] = useState<ReportPeriod>('monthly')
  const [startDate, setStartDate] = useState(todayString())
  const [endDate, setEndDate] = useState(todayString())
  const [report, setReport] = useState<SalesReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadReport = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault()
    setLoading(true)
    setError(null)
    const query = new URLSearchParams({ period })
    if (period === 'custom') {
      query.set('start_date', startDate)
      query.set('end_date', endDate)
    }
    try {
      setReport(await apiRequest<SalesReport>(`/reports/sales?${query.toString()}`))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Sales report could not be loaded.')
      setReport(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div><h1>Sales reports</h1><p>Understand revenue, collections, and popular products from completed invoices.</p></div>
      </section>

      <form className="panel report-filter" onSubmit={(event) => void loadReport(event)}>
        <label className="form-field"><span>Report period</span><select value={period} onChange={(event) => setPeriod(event.target.value as ReportPeriod)}><option value="daily">Today</option><option value="weekly">This week</option><option value="monthly">This month</option><option value="custom">Custom date range</option></select></label>
        {period === 'custom' && <>
          <label className="form-field"><span>From</span><input type="date" required value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
          <label className="form-field"><span>To</span><input type="date" required value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
        </>}
        <button type="submit" className="button button-primary" disabled={loading}><Icon name="reports" /> {loading ? 'Loading…' : 'Run report'}</button>
      </form>

      {error && <ErrorMessage message={error} onRetry={() => void loadReport()} />}
      {loading && !report ? <LoadingState label="Loading sales report…" /> : report && (
        <>
          <section className="stats-grid report-stats">
            <article className="stat-card"><div className="stat-card-top"><span className="stat-label">Net revenue</span><span className="stat-icon stat-icon-mint"><Icon name="reports" /></span></div><strong className="stat-value">{formatMoney(report.revenue)}</strong><span className="stat-note">Excludes GST and discounts already applied</span></article>
            <article className="stat-card"><div className="stat-card-top"><span className="stat-label">Total collected</span><span className="stat-icon stat-icon-blue"><Icon name="billing" /></span></div><strong className="stat-value">{formatMoney(report.gross_collected)}</strong><span className="stat-note">Includes GST paid by customers</span></article>
            <article className="stat-card"><div className="stat-card-top"><span className="stat-label">GST collected</span><span className="stat-icon stat-icon-violet"><Icon name="reports" /></span></div><strong className="stat-value">{formatMoney(report.gst_collected)}</strong><span className="stat-note">Tax included in completed invoices</span></article>
            <article className="stat-card"><div className="stat-card-top"><span className="stat-label">Invoices</span><span className="stat-icon stat-icon-amber"><Icon name="invoices" /></span></div><strong className="stat-value">{report.invoice_count.toLocaleString('en-IN')}</strong><span className="stat-note">Average bill {formatMoney(report.average_invoice_value)}</span></article>
          </section>

          <section className="report-period-note"><Icon name="calendar" size={17} /><span>Showing {report.start_date} to {report.end_date} · {report.period === 'custom' ? 'Custom period' : report.period.charAt(0).toUpperCase() + report.period.slice(1)}</span></section>

          <section className="report-lower-grid">
            <article className="panel best-sellers-panel">
              <div className="panel-heading"><div><h2>Best-selling products</h2><p>Ranked by quantity sold in this period</p></div><span className="panel-range">Top 5</span></div>
              {report.best_selling_products.length === 0 ? <EmptyState title="No sales in this period" description="Product sales will appear after bills are completed." /> : (
                <div className="table-scroll"><table className="data-table"><thead><tr><th>Product</th><th>Quantity</th><th className="align-right">Revenue</th></tr></thead><tbody>{report.best_selling_products.map((product, index) => <tr key={`${product.product_id}-${product.product_name}`}><td><span className="ranked-product"><span className="product-rank">{String(index + 1).padStart(2, '0')}</span><strong>{product.product_name}</strong></span></td><td>{product.quantity_sold}</td><td className="align-right amount-cell">{formatMoney(product.revenue)}</td></tr>)}</tbody></table></div>
              )}
            </article>
            <article className="panel profit-panel"><span className="stat-icon stat-icon-amber"><Icon name="reports" /></span><h2>Revenue is not profit</h2><p>{report.profit_note}</p><div className="profit-unavailable"><span>Profit</span><strong>{report.profit === null ? 'Not available' : formatMoney(report.profit)}</strong></div></article>
          </section>
        </>
      )}
      {!loading && !report && !error && <EmptyState title="Choose a report period" description="Run a report to see actual sales totals from your invoices." />}
    </div>
  )
}
