import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { apiRequest } from '../api'
import { EmptyState, ErrorMessage, Icon, LoadingState, Modal } from '../components/Common'
import type { Category, Product, ProductPayload } from '../types'
import type { NoticeKind } from '../App'
import { formatMoney } from '../utils/format'

interface ProductFormState {
  name: string
  barcode: string
  category_id: string
  description: string
  purchase_price: string
  selling_price: string
  gst_applicable: boolean
  gst_rate: string
  unit_of_measure: string
  is_active: boolean
}

interface CategoryFormState {
  name: string
  description: string
}

const emptyProductForm: ProductFormState = {
  name: '',
  barcode: '',
  category_id: '',
  description: '',
  purchase_price: '',
  selling_price: '',
  gst_applicable: false,
  gst_rate: '0',
  unit_of_measure: 'piece',
  is_active: true,
}

const emptyCategoryForm: CategoryFormState = { name: '', description: '' }
const productUnits = ['piece', 'kg', 'gram', 'litre', 'ml', 'packet', 'dozen', 'box']

export function ProductsPage({ notify }: { notify: (kind: NoticeKind, message: string) => void }) {
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [search, setSearch] = useState('')
  const [barcodeSearch, setBarcodeSearch] = useState('')
  const [productModal, setProductModal] = useState(false)
  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [productForm, setProductForm] = useState<ProductFormState>(emptyProductForm)
  const [categoryModal, setCategoryModal] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [categoryForm, setCategoryForm] = useState<CategoryFormState>(emptyCategoryForm)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [productRows, categoryRows] = await Promise.all([
        apiRequest<Product[]>('/products/?include_inactive=true'),
        apiRequest<Category[]>('/categories/'),
      ])
      setProducts(productRows)
      setCategories(categoryRows)
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Products could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load, retryToken])

  const categoryNames = useMemo(
    () => new Map(categories.map((category) => [category.id, category.name])),
    [categories],
  )
  const filteredProducts = useMemo(() => {
    const term = search.trim().toLocaleLowerCase()
    if (!term) return products
    return products.filter((product) =>
      [product.name, product.barcode ?? '', categoryNames.get(product.category_id ?? -1) ?? '']
        .some((value) => value.toLocaleLowerCase().includes(term)),
    )
  }, [products, search, categoryNames])

  const openNewProduct = () => {
    setEditingProduct(null)
    setProductForm({ ...emptyProductForm, category_id: categories[0] ? String(categories[0].id) : '' })
    setActionError(null)
    setProductModal(true)
  }

  const openProductEdit = (product: Product) => {
    setEditingProduct(product)
    setProductForm({
      name: product.name,
      barcode: product.barcode ?? '',
      category_id: product.category_id ? String(product.category_id) : '',
      description: product.description ?? '',
      purchase_price: product.purchase_price,
      selling_price: product.selling_price,
      gst_applicable: product.gst_applicable,
      gst_rate: product.gst_rate,
      unit_of_measure: product.unit_of_measure,
      is_active: product.is_active,
    })
    setActionError(null)
    setProductModal(true)
  }

  const saveProduct = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setActionError(null)
    const payload: ProductPayload = {
      name: productForm.name.trim(),
      barcode: productForm.barcode.trim() || null,
      category_id: Number(productForm.category_id),
      description: productForm.description.trim() || null,
      purchase_price: productForm.purchase_price,
      selling_price: productForm.selling_price,
      gst_applicable: productForm.gst_applicable,
      gst_rate: productForm.gst_applicable ? productForm.gst_rate : '0',
      unit_of_measure: productForm.unit_of_measure,
      is_active: productForm.is_active,
    }
    try {
      await apiRequest<Product>(
        editingProduct ? `/products/${editingProduct.id}` : '/products/',
        {
          method: editingProduct ? 'PUT' : 'POST',
          body: JSON.stringify(payload),
        },
      )
      setProductModal(false)
      notify('success', editingProduct ? 'Product details updated.' : 'Product added.')
      setLoading(true)
      await load()
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : 'Product could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const deactivateProduct = async (product: Product) => {
    if (!window.confirm(`Deactivate ${product.name}? It will no longer be available for new bills.`)) return
    try {
      await apiRequest<Product>(`/products/${product.id}`, { method: 'DELETE' })
      notify('success', `${product.name} was deactivated.`)
      setLoading(true)
      await load()
    } catch (reason) {
      notify('error', reason instanceof Error ? reason.message : 'Product could not be deactivated.')
    }
  }

  const searchBarcode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const barcode = barcodeSearch.trim()
    if (!barcode) return
    try {
      const product = await apiRequest<Product>(`/products/barcode/${encodeURIComponent(barcode)}`)
      setSearch(product.name)
      notify('success', `Found ${product.name}.`)
    } catch (reason) {
      notify('error', reason instanceof Error ? reason.message : 'Barcode was not found.')
    }
  }

  const openNewCategory = () => {
    setEditingCategory(null)
    setCategoryForm(emptyCategoryForm)
    setActionError(null)
    setCategoryModal(true)
  }

  const openCategoryEdit = (category: Category) => {
    setEditingCategory(category)
    setCategoryForm({ name: category.name, description: category.description ?? '' })
    setActionError(null)
    setCategoryModal(true)
  }

  const saveCategory = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setActionError(null)
    try {
      await apiRequest<Category>(
        editingCategory ? `/categories/${editingCategory.id}` : '/categories/',
        {
          method: editingCategory ? 'PUT' : 'POST',
          body: JSON.stringify({
            name: categoryForm.name.trim(),
            description: categoryForm.description.trim() || null,
          }),
        },
      )
      setCategoryModal(false)
      notify('success', editingCategory ? 'Category updated.' : 'Category created.')
      setLoading(true)
      await load()
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : 'Category could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const deleteCategory = async (category: Category) => {
    if (!window.confirm(`Delete the "${category.name}" category?`)) return
    try {
      await apiRequest<void>(`/categories/${category.id}`, { method: 'DELETE' })
      notify('success', 'Category deleted.')
      setLoading(true)
      await load()
    } catch (reason) {
      notify('error', reason instanceof Error ? reason.message : 'Category could not be deleted.')
    }
  }

  return (
    <div className="page-stack">
      <section className="page-heading-row">
        <div>
          <h1>Products</h1>
          <p>Keep product names, prices, categories, and tax details up to date.</p>
        </div>
        <button className="button button-primary" onClick={openNewProduct} disabled={categories.length === 0}>
          <Icon name="plus" /> Add product
        </button>
      </section>

      {error && <ErrorMessage message={error} onRetry={() => { setLoading(true); setError(null); setRetryToken((value) => value + 1) }} />}
      {actionError && !productModal && !categoryModal && <ErrorMessage message={actionError} />}

      <div className="product-workspace">
        <section className="panel product-panel">
          <div className="product-toolbar">
            <label className="search-field">
              <Icon name="search" />
              <input
                type="search"
                placeholder="Search products or categories"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label="Search products"
              />
            </label>
            <form className="barcode-search" onSubmit={searchBarcode}>
              <input
                value={barcodeSearch}
                onChange={(event) => setBarcodeSearch(event.target.value)}
                placeholder="Find by barcode"
                aria-label="Search by barcode"
              />
              <button className="button button-secondary" type="submit">Find</button>
            </form>
          </div>
          {loading && products.length === 0 ? (
            <LoadingState label="Loading product catalog…" />
          ) : filteredProducts.length === 0 ? (
            <EmptyState
              title={search ? 'No matching products' : 'Your catalog is empty'}
              description={search ? 'Try another product name, category, or barcode.' : 'Add your first product to start building bills.'}
              action={!search && categories.length > 0 ? <button className="button button-primary" onClick={openNewProduct}>Add a product</button> : undefined}
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table product-table">
                <thead>
                  <tr><th>Product</th><th>Category</th><th>Purchase</th><th>Selling</th><th>GST</th><th>Unit</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr>
                </thead>
                <tbody>
                  {filteredProducts.map((product) => (
                    <tr key={product.id}>
                      <td><div className="product-name-cell"><strong>{product.name}</strong><span>{product.barcode || 'No barcode'}</span></div></td>
                      <td>{categoryNames.get(product.category_id ?? -1) ?? 'Uncategorised'}</td>
                      <td>{formatMoney(product.purchase_price)}</td>
                      <td className="amount-cell">{formatMoney(product.selling_price)}</td>
                      <td>{product.gst_applicable ? `${product.gst_rate}%` : 'Not applicable'}</td>
                      <td>{product.unit_of_measure}</td>
                      <td><span className={`status-pill${product.is_active ? '' : ' status-pill-inactive'}`}>{product.is_active ? 'Active' : 'Inactive'}</span></td>
                      <td>
                        <div className="table-actions">
                          <button className="icon-button" aria-label={`Edit ${product.name}`} onClick={() => openProductEdit(product)}><Icon name="edit" size={16} /></button>
                          {product.is_active && <button className="icon-button danger-icon" aria-label={`Deactivate ${product.name}`} onClick={() => void deactivateProduct(product)}><Icon name="delete" size={16} /></button>}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {loading && products.length > 0 && <div className="refresh-indicator"><span className="spinner spinner-small" /> Refreshing catalog…</div>}
        </section>

        <section className="panel categories-panel">
          <div className="panel-heading">
            <div><h2>Categories</h2><p>{categories.length} product groups</p></div>
            <button className="icon-button add-category-button" aria-label="Add category" onClick={openNewCategory}><Icon name="plus" /></button>
          </div>
          {categories.length === 0 ? (
            <EmptyState title="No categories yet" description="Create a category before adding products." action={<button className="button button-secondary" onClick={openNewCategory}>Add category</button>} />
          ) : (
            <ul className="category-list">
              {categories.map((category) => (
                <li key={category.id}>
                  <span className="category-color-dot" />
                  <div className="category-copy"><strong>{category.name}</strong><span>{category.description || 'Product category'}</span></div>
                  <button className="icon-button" aria-label={`Edit ${category.name}`} onClick={() => openCategoryEdit(category)}><Icon name="edit" size={15} /></button>
                  <button className="icon-button danger-icon" aria-label={`Delete ${category.name}`} onClick={() => void deleteCategory(category)}><Icon name="delete" size={15} /></button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {productModal && (
        <Modal title={editingProduct ? 'Edit product' : 'Add a product'} onClose={() => setProductModal(false)} wide>
          <form className="form-grid" onSubmit={(event) => void saveProduct(event)}>
            <label className="form-field"><span>Product name *</span><input required maxLength={150} value={productForm.name} onChange={(event) => setProductForm({ ...productForm, name: event.target.value })} /></label>
            <label className="form-field"><span>Barcode <small>Optional</small></span><input maxLength={128} value={productForm.barcode} onChange={(event) => setProductForm({ ...productForm, barcode: event.target.value })} /></label>
            <label className="form-field"><span>Category *</span><select required value={productForm.category_id} onChange={(event) => setProductForm({ ...productForm, category_id: event.target.value })}><option value="">Select a category</option>{categories.map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}</select></label>
            <label className="form-field"><span>Unit *</span><select required value={productForm.unit_of_measure} onChange={(event) => setProductForm({ ...productForm, unit_of_measure: event.target.value })}>{productUnits.map((unit) => <option key={unit}>{unit}</option>)}</select></label>
            <label className="form-field"><span>Purchase price *</span><div className="input-prefix"><span>₹</span><input type="number" min="0" step="0.01" required value={productForm.purchase_price} onChange={(event) => setProductForm({ ...productForm, purchase_price: event.target.value })} /></div></label>
            <label className="form-field"><span>Selling price *</span><div className="input-prefix"><span>₹</span><input type="number" min="0" step="0.01" required value={productForm.selling_price} onChange={(event) => setProductForm({ ...productForm, selling_price: event.target.value })} /></div></label>
            <label className="form-field form-checkbox"><input type="checkbox" checked={productForm.gst_applicable} onChange={(event) => setProductForm({ ...productForm, gst_applicable: event.target.checked, gst_rate: event.target.checked ? productForm.gst_rate || '5' : '0' })} /><span>GST applies to this product</span></label>
            <label className="form-field"><span>GST rate (%)</span><input type="number" min="0" max="100" step="0.01" disabled={!productForm.gst_applicable} value={productForm.gst_applicable ? productForm.gst_rate : '0'} onChange={(event) => setProductForm({ ...productForm, gst_rate: event.target.value })} /></label>
            <label className="form-field form-span-two"><span>Description</span><textarea rows={3} value={productForm.description} onChange={(event) => setProductForm({ ...productForm, description: event.target.value })} /></label>
            {editingProduct && <label className="form-field form-checkbox"><input type="checkbox" checked={productForm.is_active} onChange={(event) => setProductForm({ ...productForm, is_active: event.target.checked })} /><span>Product is active</span></label>}
            {actionError && <p className="form-error form-span-two" role="alert">{actionError}</p>}
            <div className="modal-actions form-span-two"><button type="button" className="button button-secondary" onClick={() => setProductModal(false)}>Cancel</button><button type="submit" className="button button-primary" disabled={saving}>{saving ? 'Saving…' : editingProduct ? 'Save changes' : 'Add product'}</button></div>
          </form>
        </Modal>
      )}

      {categoryModal && (
        <Modal title={editingCategory ? 'Edit category' : 'Add category'} onClose={() => setCategoryModal(false)}>
          <form className="form-stack" onSubmit={(event) => void saveCategory(event)}>
            <label className="form-field"><span>Category name *</span><input required maxLength={100} value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} /></label>
            <label className="form-field"><span>Description</span><textarea rows={3} value={categoryForm.description} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} /></label>
            {actionError && <p className="form-error" role="alert">{actionError}</p>}
            <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setCategoryModal(false)}>Cancel</button><button type="submit" className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save category'}</button></div>
          </form>
        </Modal>
      )}
    </div>
  )
}
