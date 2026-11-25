import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { apiRequest } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState, Modal } from '../components/Common'
import type { Customer, CustomerPayload, Invoice } from '../types'
import type { NoticeKind } from '../App'
import { formatDate, formatMoney } from '../utils/format'

const blankCustomer: CustomerPayload = { name: '', email: null, phone: null, address: null }

export function CustomersPage({ notify }: { notify: (kind: NoticeKind, message: string) => void }) {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [formOpen, setFormOpen] = useState(false)
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null)
  const [form, setForm] = useState<CustomerPayload>(blankCustomer)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [viewingCustomer, setViewingCustomer] = useState<Customer | null>(null)
  const [customerInvoices, setCustomerInvoices] = useState<Invoice[]>([])
  const [invoicesLoading, setInvoicesLoading] = useState(false)
  const [invoiceError, setInvoiceError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const query = new URLSearchParams({ limit: '250' })
      if (search.trim()) query.set('search', search.trim())
      setCustomers(await apiRequest<Customer[]>(`/customers/?${query.toString()}`))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Customers could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [load, retryToken, search])

  const startCreate = () => {
    setEditingCustomer(null)
    setForm(blankCustomer)
    setFormError(null)
    setFormOpen(true)
  }

  const startEdit = (customer: Customer) => {
    setViewingCustomer(null)
    setEditingCustomer(customer)
    setForm({ name: customer.name, email: customer.email, phone: customer.phone, address: customer.address })
    setFormError(null)
    setFormOpen(true)
  }

  const saveCustomer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setFormError(null)
    const payload: CustomerPayload = {
      name: form.name.trim(),
      email: form.email?.trim() || null,
      phone: form.phone?.trim() || null,
      address: form.address?.trim() || null,
    }
    try {
      await apiRequest<Customer>(
        editingCustomer ? `/customers/${editingCustomer.id}` : '/customers/',
        { method: editingCustomer ? 'PUT' : 'POST', body: JSON.stringify(payload) },
      )
      setFormOpen(false)
      notify('success', editingCustomer ? 'Customer details updated.' : 'Customer added.')
      await load()
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : 'Customer could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const viewCustomer = async (customer: Customer) => {
    setViewingCustomer(customer)
    setCustomerInvoices([])
    setInvoiceError(null)
    setInvoicesLoading(true)
    try {
      setCustomerInvoices(await apiRequest<Invoice[]>(`/customers/${customer.id}/invoices`))
    } catch (reason) {
      setInvoiceError(reason instanceof Error ? reason.message : 'Purchase history could not be loaded.')
    } finally {
      setInvoicesLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div><h1>Customers</h1><p>Customer details are optional when you create a bill.</p></div>
        <button className="button button-primary" onClick={startCreate}><Icon name="plus" /> Add customer</button>
      </section>
      {error && <ErrorMessage message={error} onRetry={() => setRetryToken((value) => value + 1)} />}
      <section className="panel customer-list-panel">
        <div className="list-toolbar">
          <label className="search-field"><Icon name="search" /><input type="search" placeholder="Search name, email, or phone" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search customers" /></label>
          <span className="record-count">{customers.length} {customers.length === 1 ? 'customer' : 'customers'}</span>
        </div>
        {loading && customers.length === 0 ? <LoadingState label="Loading customers…" /> : customers.length === 0 ? (
          <EmptyState title={search ? 'No matching customers' : 'No customers yet'} description={search ? 'Try another name, email, or phone number.' : 'Add a customer to keep their contact details and previous invoices together.'} action={!search ? <button className="button button-secondary" onClick={startCreate}>Add customer</button> : undefined} />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Customer</th><th>Phone</th><th>Email</th><th>Address</th><th>Added</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>{customers.map((customer) => (
                <tr key={customer.id}>
                  <td><button className="customer-name-button" onClick={() => void viewCustomer(customer)}><span className="customer-avatar">{customer.name.slice(0, 1).toLocaleUpperCase()}</span><strong>{customer.name}</strong></button></td>
                  <td>{customer.phone || '—'}</td><td>{customer.email || '—'}</td><td className="customer-address">{customer.address || '—'}</td><td className="muted-cell">{formatDate(customer.created_at)}</td>
                  <td><div className="table-actions"><button className="icon-button" aria-label={`View ${customer.name}`} onClick={() => void viewCustomer(customer)}><Icon name="customers" size={16} /></button><button className="icon-button" aria-label={`Edit ${customer.name}`} onClick={() => startEdit(customer)}><Icon name="edit" size={16} /></button></div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {loading && customers.length > 0 && <div className="refresh-indicator"><span className="spinner spinner-small" /> Updating customers…</div>}
      </section>

      {formOpen && <Modal title={editingCustomer ? 'Edit customer' : 'Add customer'} onClose={() => setFormOpen(false)}>
        <form className="form-stack" onSubmit={(event) => void saveCustomer(event)}>
          <label className="form-field"><span>Full name *</span><input required maxLength={150} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label className="form-field"><span>Phone number</span><input type="tel" maxLength={32} value={form.phone ?? ''} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
          <label className="form-field"><span>Email address</span><input type="email" maxLength={254} value={form.email ?? ''} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
          <label className="form-field"><span>Address</span><textarea rows={3} value={form.address ?? ''} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label>
          {formError && <p className="form-error" role="alert">{formError}</p>}
          <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setFormOpen(false)}>Cancel</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : editingCustomer ? 'Save changes' : 'Add customer'}</button></div>
        </form>
      </Modal>}

      {viewingCustomer && <Modal title={viewingCustomer.name} onClose={() => setViewingCustomer(null)} wide>
        <div className="customer-detail">
          <div className="customer-detail-contact"><div><span>Phone</span><strong>{viewingCustomer.phone || 'Not provided'}</strong></div><div><span>Email</span><strong>{viewingCustomer.email || 'Not provided'}</strong></div><div><span>Address</span><strong>{viewingCustomer.address || 'Not provided'}</strong></div></div>
          <div className="customer-history-heading"><div><h3>Previous invoices</h3><p>Completed purchases linked to this customer</p></div><button className="button button-secondary" onClick={() => startEdit(viewingCustomer)}><Icon name="edit" size={16} /> Edit customer</button></div>
          {invoiceError && <ErrorMessage message={invoiceError} />}
          {invoicesLoading ? <LoadingState label="Loading purchase history…" /> : customerInvoices.length === 0 ? <EmptyState title="No previous invoices" description="Invoices selected with this customer will appear here." /> : (
            <div className="table-scroll"><table className="data-table"><thead><tr><th>Invoice</th><th>Date</th><th>Payment</th><th className="align-right">Total</th></tr></thead><tbody>{customerInvoices.map((invoice) => <tr key={invoice.id}><td><strong>{invoice.invoice_number}</strong></td><td>{formatDate(invoice.created_at)}</td><td>{invoice.payments[0]?.payment_method.toUpperCase() || '—'}</td><td className="align-right amount-cell">{formatMoney(invoice.total_amount)}</td></tr>)}</tbody></table></div>
          )}
        </div>
      </Modal>}
    </div>
  )
}
