export interface Category {
  id: number
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface Product {
  id: number
  name: string
  barcode: string | null
  category_id: number | null
  description: string | null
  purchase_price: string
  selling_price: string
  gst_applicable: boolean
  gst_rate: string
  unit_of_measure: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ProductPayload {
  name: string
  barcode: string | null
  category_id: number
  description: string | null
  purchase_price: string
  selling_price: string
  gst_applicable: boolean
  gst_rate: string
  unit_of_measure: string
  is_active: boolean
}

export interface Customer {
  id: number
  name: string
  email: string | null
  phone: string | null
  address: string | null
  created_at: string
  updated_at: string
}

export interface CustomerPayload {
  name: string
  email: string | null
  phone: string | null
  address: string | null
}

export interface InvoiceItem {
  id: number
  product_id: number
  product_name: string
  unit_of_measure: string
  quantity: string
  unit_price: string
  gst_applicable: boolean
  gst_rate: string
  line_subtotal: string
  discount_amount: string
  taxable_value: string
  non_taxable_value: string
  tax_amount: string
  line_total: string
}

export interface Payment {
  id: number
  amount: string
  payment_method: 'cash' | 'upi' | string
  payment_status: string
  created_at: string
}

export interface Invoice {
  id: number
  invoice_number: string
  customer_id: number | null
  customer_name: string | null
  subtotal: string
  discount_amount: string
  taxable_amount: string
  non_taxable_amount: string
  tax_total: string
  total_amount: string
  created_at: string
  updated_at: string
  items: InvoiceItem[]
  payments: Payment[]
}

export interface InvoiceQuoteLine {
  product_id: number
  product_name: string
  unit_of_measure: string
  quantity: string
  unit_price: string
  gst_applicable: boolean
  gst_rate: string
  line_subtotal: string
  discount_amount: string
  taxable_value: string
  non_taxable_value: string
  tax_amount: string
  line_total: string
}

export interface InvoiceQuote {
  subtotal: string
  discount_amount: string
  taxable_amount: string
  non_taxable_amount: string
  tax_total: string
  total_amount: string
  items: InvoiceQuoteLine[]
}

export interface SalesOverviewPoint {
  date: string
  revenue: string
  invoice_count: number
}

export interface DashboardData {
  today_revenue: string
  today_invoice_count: number
  monthly_revenue: string
  total_invoices: number
  total_customers: number
  recent_invoices: Invoice[]
  sales_overview: SalesOverviewPoint[]
  profit: string | null
  profit_note: string
}

export interface BestSellingProduct {
  product_id: number
  product_name: string
  quantity_sold: string
  revenue: string
}

export interface SalesReport {
  period: string
  start_date: string
  end_date: string
  revenue: string
  gross_collected: string
  gst_collected: string
  invoice_count: number
  average_invoice_value: string
  best_selling_products: BestSellingProduct[]
  profit: string | null
  profit_note: string
}

export interface AuthStatus {
  configured: boolean
  authenticated: boolean
  csrf_token: string | null
}

export interface AssistantSource {
  label: string
  detail: string | null
}

export interface AssistantReply {
  answer: string
  language: 'en' | 'te'
  intent: string
  sources: AssistantSource[]
}

export interface AssistantDocument {
  id: number
  filename: string
  created_at: string
  chunk_count: number
}

export interface AssistantStatus {
  chat_configured: boolean
  embeddings_configured: boolean
}
