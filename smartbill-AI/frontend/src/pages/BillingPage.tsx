import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { apiRequest, downloadInvoicePdf } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState } from '../components/Common'
import type { Customer, Invoice, InvoiceQuote, Product } from '../types'
import type { NoticeKind } from '../App'
import { formatMoney } from '../utils/format'

interface CartLine {
  product: Product
  quantity: string
}

function canonicalDecimal(value: string): string {
  const [whole, fraction = ''] = value.split('.')
  const normalizedWhole = whole.replace(/^0+(?=\d)/, '') || '0'
  const normalizedFraction = fraction.replace(/0+$/, '')
  return normalizedFraction
    ? `${normalizedWhole}.${normalizedFraction}`
    : normalizedWhole
}

export function BillingPage({
  notify,
  onComplete,
}: {
  notify: (kind: NoticeKind, message: string) => void
  onComplete: () => void
}) {
  const [products, setProducts] = useState<Product[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [cart, setCart] = useState<CartLine[]>([])
  const [search, setSearch] = useState('')
  const [barcode, setBarcode] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [discount, setDiscount] = useState('0.00')
  const [paymentMethod, setPaymentMethod] = useState<'cash' | 'upi'>('cash')
  const [quote, setQuote] = useState<InvoiceQuote | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [quoteError, setQuoteError] = useState<string | null>(null)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [completedInvoice, setCompletedInvoice] = useState<Invoice | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const requestId = useRef(0)
  const checkoutKeys = useRef(new Map<string, string>())

  useEffect(() => {
    let active = true
    Promise.all([
      apiRequest<Product[]>('/products/'),
      apiRequest<Customer[]>('/customers/'),
    ]).then(([productRows, customerRows]) => {
      if (!active) return
      setProducts(productRows)
      setCustomers(customerRows)
    }).catch((reason: unknown) => {
      if (active) setCheckoutError(reason instanceof Error ? reason.message : 'Checkout data could not be loaded.')
    }).finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])

  useEffect(() => {
    const currentRequestId = ++requestId.current
    if (cart.length === 0) return

    const timer = window.setTimeout(async () => {
      setQuoteLoading(true)
      setQuoteError(null)
      try {
        const result = await apiRequest<InvoiceQuote>('/invoices/quote', {
          method: 'POST',
          body: JSON.stringify({
            items: cart.map((line) => ({
              product_id: line.product.id,
              quantity: line.quantity,
            })),
            discount_amount: discount || '0',
          }),
        })
        if (currentRequestId === requestId.current) setQuote(result)
      } catch (reason) {
        if (currentRequestId === requestId.current) {
          setQuote(null)
          setQuoteError(reason instanceof Error ? reason.message : 'Bill totals could not be calculated.')
        }
      } finally {
        if (currentRequestId === requestId.current) setQuoteLoading(false)
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [cart, discount])

  const visibleProducts = useMemo(() => {
    const term = search.trim().toLocaleLowerCase()
    if (!term) return products.slice(0, 8)
    return products.filter((product) =>
      product.name.toLocaleLowerCase().includes(term) ||
      (product.barcode ?? '').toLocaleLowerCase().includes(term),
    ).slice(0, 12)
  }, [products, search])

  const invalidateQuote = () => {
    setQuote(null)
    setQuoteError(null)
    setQuoteLoading(cart.length > 0)
  }

  const addProduct = (product: Product) => {
    setCompletedInvoice(null)
    invalidateQuote()
    setCart((current) => {
      const existing = current.find((line) => line.product.id === product.id)
      if (existing) return current.map((line) => line.product.id === product.id
        ? { ...line, quantity: String(Number(line.quantity) + 1) }
        : line)
      return [...current, { product, quantity: '1' }]
    })
  }

  const updateQuantity = (productId: number, quantity: string) => {
    invalidateQuote()
    setCart((current) => current.map((line) => line.product.id === productId ? { ...line, quantity } : line))
  }

  const removeProduct = (productId: number) => {
    if (cart.length === 1 && cart[0].product.id === productId) {
      setQuote(null)
      setQuoteError(null)
      setQuoteLoading(false)
    } else {
      invalidateQuote()
    }
    setCart((current) => current.filter((line) => line.product.id !== productId))
  }

  const clearCart = () => {
    checkoutKeys.current.clear()
    setCart([])
    setQuote(null)
    setQuoteError(null)
    setQuoteLoading(false)
  }

  const findBarcode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const value = barcode.trim()
    if (!value) return
    try {
      const product = await apiRequest<Product>(`/products/barcode/${encodeURIComponent(value)}`)
      addProduct(product)
      setBarcode('')
      setSearch('')
    } catch (reason) {
      notify('error', reason instanceof Error ? reason.message : 'Barcode was not found.')
    }
  }

  const completeBill = async () => {
    if (!quote || quoteLoading || quoteError || cart.length === 0) return
    setSaving(true)
    setCheckoutError(null)
    const items = cart.map((line) => ({
      product_id: line.product.id,
      quantity: line.quantity,
    }))
    const customer = customerId ? Number(customerId) : null
    const discountAmount = discount || '0'
    const fingerprint = JSON.stringify({
      customer_id: customer,
      discount_amount: canonicalDecimal(discountAmount),
      items: items
        .map((item) => ({
          product_id: item.product_id,
          quantity: canonicalDecimal(item.quantity),
        }))
        .sort((left, right) => left.product_id - right.product_id),
      payment_amount: canonicalDecimal(quote.total_amount),
      payment_method: paymentMethod,
    })
    const idempotencyKey =
      checkoutKeys.current.get(fingerprint) ?? crypto.randomUUID()
    checkoutKeys.current.set(fingerprint, idempotencyKey)
    try {
      const invoice = await apiRequest<Invoice>('/invoices/', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({
          items,
          customer_id: customer,
          discount_amount: discountAmount,
          payment_method: paymentMethod,
          payment_amount: quote.total_amount,
        }),
      })
      setCompletedInvoice(invoice)
      clearCart()
      setCustomerId('')
      setDiscount('0.00')
      onComplete()
      notify('success', `Bill ${invoice.invoice_number} completed successfully.`)
    } catch (reason) {
      setCheckoutError(reason instanceof Error ? reason.message : 'The bill could not be completed.')
    } finally {
      setSaving(false)
    }
  }

  const downloadCompletedPdf = async () => {
    if (!completedInvoice) return
    setPdfLoading(true)
    try {
      await downloadInvoicePdf(completedInvoice.id)
    } catch (reason) {
      notify('error', reason instanceof Error ? reason.message : 'Invoice PDF could not be downloaded.')
    } finally {
      setPdfLoading(false)
    }
  }

  if (loading) return <LoadingState label="Preparing checkout…" />

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div><h1>New bill</h1><p>Choose products, review the server-calculated total, and take payment.</p></div>
        <span className="pos-secure-note"><Icon name="check" size={16} /> Prices and tax confirmed by SmartBill</span>
      </section>

      {checkoutError && <ErrorMessage message={checkoutError} />}
      {completedInvoice && (
        <section className="checkout-success">
          <span className="checkout-success-icon"><Icon name="check" size={20} /></span>
          <div className="checkout-success-copy"><strong>Bill completed</strong><span>{completedInvoice.invoice_number} · {formatMoney(completedInvoice.total_amount)}</span></div>
          <button className="button button-secondary" onClick={() => void downloadCompletedPdf()} disabled={pdfLoading}>
            <Icon name="download" /> {pdfLoading ? 'Preparing PDF…' : 'Download / print'}
          </button>
          <button className="icon-button" aria-label="Dismiss invoice confirmation" onClick={() => setCompletedInvoice(null)}><Icon name="close" size={16} /></button>
        </section>
      )}

      <div className="pos-layout">
        <section className="panel pos-catalog-panel">
          <div className="pos-catalog-heading">
            <div><h2>Choose products</h2><p>{products.length} active products</p></div>
          </div>
          <label className="search-field pos-product-search">
            <Icon name="search" />
            <input autoFocus type="search" placeholder="Search product name" value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <form className="barcode-entry" onSubmit={(event) => void findBarcode(event)}>
            <Icon name="barcode" size={18} />
            <input value={barcode} onChange={(event) => setBarcode(event.target.value)} placeholder="Scan or enter barcode" aria-label="Scan or enter barcode" />
            <button type="submit" className="button button-secondary">Add</button>
          </form>
          <div className="pos-product-list">
            {visibleProducts.length === 0 ? (
              <EmptyState title="No products found" description="Try another search or add products in the Products page." />
            ) : visibleProducts.map((product) => (
              <button className="pos-product-option" key={product.id} onClick={() => addProduct(product)}>
                <span className="pos-product-initial">{product.name.slice(0, 1).toLocaleUpperCase()}</span>
                <span className="pos-product-details"><strong>{product.name}</strong><small>{product.gst_applicable ? `GST ${product.gst_rate}%` : 'No GST'} · {product.unit_of_measure}</small></span>
                <strong className="pos-product-price">{formatMoney(product.selling_price)}</strong>
                <span className="pos-add-mark"><Icon name="plus" size={15} /></span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel cart-panel">
          <div className="cart-heading">
            <div><h2>Current bill</h2><p>{cart.length} {cart.length === 1 ? 'product' : 'products'}</p></div>
            {cart.length > 0 && <button className="button button-quiet" onClick={clearCart}>Clear</button>}
          </div>

          {cart.length === 0 ? (
            <div className="cart-empty"><div className="cart-empty-icon"><Icon name="billing" size={22} /></div><strong>Your bill is empty</strong><span>Choose or scan a product to get started.</span></div>
          ) : (
            <div className="cart-lines">
              {cart.map((line) => {
                const quoteLine = quote?.items.find((item) => item.product_id === line.product.id)
                return (
                  <article className="cart-line" key={line.product.id}>
                    <div className="cart-line-main">
                      <strong>{line.product.name}</strong>
                      <span>{formatMoney(line.product.selling_price)} / {line.product.unit_of_measure}{line.product.gst_applicable ? ` · GST ${line.product.gst_rate}%` : ''}</span>
                    </div>
                    <label className="quantity-control"><span className="visually-hidden">Quantity for {line.product.name}</span><input type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => updateQuantity(line.product.id, event.target.value)} /></label>
                    <strong className="cart-line-total">{quoteLine ? formatMoney(quoteLine.line_total) : '—'}</strong>
                    <button className="icon-button danger-icon" aria-label={`Remove ${line.product.name}`} onClick={() => removeProduct(line.product.id)}><Icon name="delete" size={16} /></button>
                  </article>
                )
              })}
            </div>
          )}

          <div className="checkout-fields">
            <label className="form-field"><span>Customer <small>Optional</small></span><select value={customerId} onChange={(event) => setCustomerId(event.target.value)}><option value="">Walk-in customer</option>{customers.map((customer) => <option value={customer.id} key={customer.id}>{customer.name}{customer.phone ? ` · ${customer.phone}` : ''}</option>)}</select></label>
            <label className="form-field"><span>Bill discount</span><div className="input-prefix"><span>₹</span><input type="number" min="0" step="0.01" value={discount} onChange={(event) => { invalidateQuote(); setDiscount(event.target.value) }} /></div></label>
          </div>

          {quoteError && <p className="form-error quote-error" role="alert">{quoteError}</p>}
          <div className="bill-totals" aria-live="polite">
            <div><span>Item subtotal</span><span>{quote ? formatMoney(quote.subtotal) : '—'}</span></div>
            <div><span>Discount</span><span>{quote ? `− ${formatMoney(quote.discount_amount)}` : '—'}</span></div>
            <div><span>Taxable value</span><span>{quote ? formatMoney(quote.taxable_amount) : '—'}</span></div>
            <div><span>Non-taxable value</span><span>{quote ? formatMoney(quote.non_taxable_amount) : '—'}</span></div>
            <div><span>GST</span><span>{quote ? formatMoney(quote.tax_total) : '—'}</span></div>
            <div className="bill-total"><strong>Amount due</strong><strong>{quoteLoading ? <span className="spinner spinner-small" /> : quote ? formatMoney(quote.total_amount) : '—'}</strong></div>
          </div>

          <fieldset className="payment-selector">
            <legend>Payment method</legend>
            <label className={`payment-option${paymentMethod === 'cash' ? ' payment-option-selected' : ''}`}><input type="radio" name="payment" value="cash" checked={paymentMethod === 'cash'} onChange={() => setPaymentMethod('cash')} /><span className="payment-option-icon"><Icon name="cash" size={17} /></span><span><strong>Cash</strong><small>Pay with cash</small></span></label>
            <label className={`payment-option${paymentMethod === 'upi' ? ' payment-option-selected' : ''}`}><input type="radio" name="payment" value="upi" checked={paymentMethod === 'upi'} onChange={() => setPaymentMethod('upi')} /><span className="payment-option-icon"><Icon name="upi" size={17} /></span><span><strong>UPI</strong><small>Digital payment</small></span></label>
          </fieldset>

          <button className="button button-primary complete-bill-button" onClick={() => void completeBill()} disabled={cart.length === 0 || !quote || quoteLoading || Boolean(quoteError) || saving}>
            {saving ? 'Completing bill…' : <>Complete bill <Icon name="arrow" /></>}
          </button>
          <p className="checkout-footnote">Full payment is collected at checkout. GST is calculated by product and confirmed by the backend.</p>
        </section>
      </div>
    </div>
  )
}
