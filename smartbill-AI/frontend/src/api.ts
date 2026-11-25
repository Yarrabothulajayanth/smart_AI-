const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

if (!configuredBaseUrl) {
  throw new Error('VITE_API_BASE_URL is not set. Add it to frontend/.env.')
}

const API_BASE_URL = configuredBaseUrl.replace(/\/+$/, '')
let csrfToken: string | null = null

function updateCsrfToken(path: string, payload: unknown): void {
  if (
    !['/auth/status', '/auth/login', '/auth/logout'].includes(path) ||
    typeof payload !== 'object' ||
    payload === null ||
    !('csrf_token' in payload)
  ) {
    return
  }
  csrfToken = typeof payload.csrf_token === 'string' ? payload.csrf_token : null
}

function errorMessage(payload: unknown, fallback: string): string {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload &&
    typeof payload.detail === 'string'
  ) {
    return payload.detail
  }
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload &&
    Array.isArray(payload.detail)
  ) {
    const messages = payload.detail.flatMap((issue) => {
      if (typeof issue !== 'object' || issue === null || !('msg' in issue) || typeof issue.msg !== 'string') {
        return []
      }
      const location = 'loc' in issue && Array.isArray(issue.loc)
        ? issue.loc.map(String).join('.')
        : ''
      return [`${location ? `${location}: ` : ''}${issue.msg}`]
    })
    if (messages.length > 0) return messages.join('; ')
  }
  return fallback
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const method = (options.method ?? 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: options.credentials ?? 'include',
      headers,
    })
  } catch {
    throw new Error(
      `Could not connect to SmartBill API at ${API_BASE_URL}. Check that the backend is running.`,
    )
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (
      response.status === 401 &&
      !path.startsWith('/auth/')
    ) {
      csrfToken = null
      window.dispatchEvent(new CustomEvent('smartbill-auth-required'))
    }
    throw new Error(errorMessage(body, `Request failed (${response.status}).`))
  }
  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json()
  updateCsrfToken(path, payload)
  return payload as T
}

export async function downloadInvoicePdf(invoiceId: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/invoices/${invoiceId}/pdf`, {
      credentials: 'include',
    })
  } catch {
    throw new Error('Could not connect to the backend to download this invoice.')
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('smartbill-auth-required'))
    }
    throw new Error(errorMessage(body, `PDF download failed (${response.status}).`))
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = `invoice-${invoiceId}.pdf`
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}
