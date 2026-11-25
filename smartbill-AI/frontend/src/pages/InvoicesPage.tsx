import { useCallback, useEffect, useState } from 'react'
import { apiRequest, downloadInvoicePdf } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState, Modal, StatusPill } from '../components/Common'
import type { Invoice } from '../types'
import { formatDate, formatMoney } from '../utils/format'

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] ?? character)
}

function printInvoice(invoice: Invoice) {
  const printWindow = window.open('', '_blank')
  if (!printWindow) throw new Error('Allow pop-ups to print this invoice.')
  printWindow.opener = null
  const rows = invoice.items.map((item) => `
    <tr>
      <td>${escapeHtml(item.product_name)}<small>${item.gst_applicable ? `GST ${escapeHtml(item.gst_rate)}%` : 'No GST'}</small></td>
      <td>${escapeHtml(item.quantity)} ${escapeHtml(item.unit_of_measure)}</td>
      <td>₹${escapeHtml(item.unit_price)}</td>
      <td>₹${escapeHtml(item.discount_amount)}</td>
      <td>₹${escapeHtml(item.tax_amount)}</td>
      <td class="right">₹${escapeHtml(item.line_total)}</td>
    </tr>`).join('')
  const payment = invoice.payments[0]
  printWindow.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(invoice.invoice_number)}</title>
    <style>
      *{box-sizing:border-box}body{font:14px Arial,sans-serif;color:#17233b;margin:34px auto;max-width:760px;padding:0 20px}
      header{display:flex;justify-content:space-between;border-bottom:2px solid #1b7c68;padding-bottom:18px}
      h1{font-size:23px;margin:0 0 6px}p{margin:4px 0;color:#58657a}.label{color:#7a8495;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
      table{border-collapse:collapse;width:100%;margin-top:24px}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #e5e9ef}th{font-size:11px;text-transform:uppercase;color:#69758a}
      td small{display:block;color:#69758a;margin-top:3px}.right{text-align:right}.totals{margin:20px 0 0 auto;width:280px}.totals div{display:flex;justify-content:space-between;padding:6px 0}
      .grand{border-top:2px solid #1b7c68;margin-top:7px;padding-top:12px!important;font-size:18px;font-weight:bold}
      footer{margin-top:32px;text-align:center;color:#69758a;font-size:12px}
      @media print{body{margin:0 auto;padding:10mm;max-width:none}@page{size:A4;margin:12mm}}
    </style></head><body>
    <header><div><h1>SmartBill AI</h1><p>Retail invoice</p></div><div style="text-align:right"><div class="label">Invoice</div><strong>${escapeHtml(invoice.invoice_number)}</strong><p>${escapeHtml(formatDate(invoice.created_at))}</p></div></header>
    <p style="margin-top:20px"><span class="label">Customer</span><br>${escapeHtml(invoice.customer_name || 'Walk-in customer')}</p>
    <table><thead><tr><th>Product</th><th>Quantity</th><th>Price</th><th>Discount</th><th>GST</th><th class="right">Amount</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="totals"><div><span>Subtotal</span><strong>₹${escapeHtml(invoice.subtotal)}</strong></div><div><span>Discount</span><strong>− ₹${escapeHtml(invoice.discount_amount)}</strong></div><div><span>GST</span><strong>₹${escapeHtml(invoice.tax_total)}</strong></div><div class="grand"><span>Payable</span><span>₹${escapeHtml(invoice.total_amount)}</span></div></div>
    <p style="margin-top:18px"><span class="label">Payment</span><br>${escapeHtml(payment?.payment_method.toUpperCase() || '—')} · ${escapeHtml(payment?.payment_status || '—')}</p>
    <footer>Thank you for shopping with us.</footer><script>window.onload=()=>window.print()</script></body></html>`)
  printWindow.document.close()
}

export function InvoicesPage({ refreshToken }: { refreshToken: number }) {
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [printError, setPrintError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const query = new URLSearchParams({ limit: '100', offset: '0' })
      if (search.trim()) query.set('search', search.trim())
      const result = await apiRequest<Invoice[]>(`/invoices/?${query.toString()}`)
      setInvoices(result)
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Invoices could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [load, refreshToken, retryToken, search])

  const openInvoice = async (invoice: Invoice) => {
    setSelectedInvoice(invoice)
    setPrintError(null)
    try {
      const fullInvoice = await apiRequest<Invoice>(`/invoices/${invoice.id}`)
      setSelectedInvoice(fullInvoice)
    } catch (reason) {
      setPrintError(reason instanceof Error ? reason.message : 'Invoice details could not be loaded.')
    }
  }

  const downloadPdf = async (invoice: Invoice) => {
    setPdfLoading(true)
    setPrintError(null)
    try {
      await downloadInvoicePdf(invoice.id)
    } catch (reason) {
      setPrintError(reason instanceof Error ? reason.message : 'PDF could not be downloaded.')
    } finally {
      setPdfLoading(false)
    }
  }

  const printSelectedInvoice = () => {
    if (!selectedInvoice) return
    try {
      printInvoice(selectedInvoice)
    } catch (reason) {
      setPrintError(reason instanceof Error ? reason.message : 'Invoice could not be printed.')
    }
  }

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div><h1>Invoices</h1><p>Search completed bills, view their details, or print a customer copy.</p></div>
        <span className="record-count">{invoices.length} recent {invoices.length === 1 ? 'invoice' : 'invoices'}</span>
      </section>
      {error && <ErrorMessage message={error} onRetry={() => { setLoading(true); setError(null); setRetryToken((value) => value + 1) }} />}
      <section className="panel invoice-list-panel">
        <div className="list-toolbar">
          <label className="search-field"><Icon name="search" /><input type="search" placeholder="Search invoice number or customer name" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search invoices" /></label>
        </div>
        {loading && invoices.length === 0 ? <LoadingState label="Loading invoices…" /> : invoices.length === 0 ? (
          <EmptyState title={search ? 'No matching invoices' : 'No invoices yet'} description={search ? 'Try another invoice number or customer name.' : 'Completed bills will appear here.'} />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Payment</th><th>Status</th><th className="align-right">Total</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>{invoices.map((invoice) => {
                const payment = invoice.payments[0]
                return (
                  <tr key={invoice.id}>
                    <td><button className="link-button" onClick={() => void openInvoice(invoice)}>{invoice.invoice_number}</button></td>
                    <td className="muted-cell">{formatDate(invoice.created_at)}</td>
                    <td>{invoice.customer_name || 'Walk-in customer'}</td>
                    <td><span className="payment-method">{payment?.payment_method.toUpperCase() || '—'}</span></td>
                    <td><StatusPill>{payment?.payment_status || 'Unknown'}</StatusPill></td>
                    <td className="align-right amount-cell">{formatMoney(invoice.total_amount)}</td>
                    <td><div className="table-actions"><button className="icon-button" aria-label={`View ${invoice.invoice_number}`} onClick={() => void openInvoice(invoice)}><Icon name="edit" size={16} /></button><button className="icon-button" aria-label={`Download ${invoice.invoice_number} PDF`} onClick={() => void downloadPdf(invoice)}><Icon name="download" size={16} /></button></div></td>
                  </tr>
                )
              })}</tbody>
            </table>
          </div>
        )}
        {loading && invoices.length > 0 && <div className="refresh-indicator"><span className="spinner spinner-small" /> Refreshing invoices…</div>}
      </section>

      {selectedInvoice && (
        <Modal title={`Invoice ${selectedInvoice.invoice_number}`} onClose={() => setSelectedInvoice(null)} wide>
          <div className="invoice-detail">
            <div className="invoice-detail-meta"><div><span>Customer</span><strong>{selectedInvoice.customer_name || 'Walk-in customer'}</strong></div><div><span>Date</span><strong>{formatDate(selectedInvoice.created_at)}</strong></div><div><span>Payment</span><strong>{selectedInvoice.payments[0]?.payment_method.toUpperCase() || '—'} · {selectedInvoice.payments[0]?.payment_status || '—'}</strong></div></div>
            {printError && <ErrorMessage message={printError} />}
            <div className="table-scroll invoice-items-scroll"><table className="data-table"><thead><tr><th>Product</th><th>Qty / unit</th><th>Price</th><th>Discount</th><th>GST</th><th className="align-right">Amount</th></tr></thead><tbody>{selectedInvoice.items.map((item) => <tr key={item.id}><td><strong>{item.product_name}</strong><span className="table-subtext">{item.gst_applicable ? `GST ${item.gst_rate}%` : 'No GST'}</span></td><td>{item.quantity} {item.unit_of_measure}</td><td>{formatMoney(item.unit_price)}</td><td>{formatMoney(item.discount_amount)}</td><td>{formatMoney(item.tax_amount)}</td><td className="align-right amount-cell">{formatMoney(item.line_total)}</td></tr>)}</tbody></table></div>
            <div className="invoice-detail-totals"><div><span>Subtotal</span><strong>{formatMoney(selectedInvoice.subtotal)}</strong></div><div><span>Discount</span><strong>− {formatMoney(selectedInvoice.discount_amount)}</strong></div><div><span>GST</span><strong>{formatMoney(selectedInvoice.tax_total)}</strong></div><div className="invoice-detail-total"><strong>Final payable</strong><strong>{formatMoney(selectedInvoice.total_amount)}</strong></div></div>
            <div className="modal-actions"><button className="button button-secondary" onClick={printSelectedInvoice}><Icon name="print" /> Print</button><button className="button button-primary" onClick={() => void downloadPdf(selectedInvoice)} disabled={pdfLoading}><Icon name="download" /> {pdfLoading ? 'Preparing…' : 'Download PDF'}</button></div>
          </div>
        </Modal>
      )}
    </div>
  )
}
