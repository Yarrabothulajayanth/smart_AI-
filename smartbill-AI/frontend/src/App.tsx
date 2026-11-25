import { useEffect, useState } from 'react'
import { apiRequest } from './api'
import { Icon, type IconName } from './components/Common'
import { DashboardPage } from './pages/DashboardPage'
import { BillingPage } from './pages/BillingPage'
import { ProductsPage } from './pages/ProductsPage'
import { InvoicesPage } from './pages/InvoicesPage'
import { CustomersPage } from './pages/CustomersPage'
import { ReportsPage } from './pages/ReportsPage'
import { AssistantPage } from './pages/AssistantPage'
import { SignInPage } from './pages/SignInPage'
import type { AuthStatus } from './types'
import './App.css'

export type PageKey = 'dashboard' | 'billing' | 'products' | 'invoices' | 'customers' | 'reports' | 'assistant'
export type NoticeKind = 'success' | 'error'

interface Notice {
  kind: NoticeKind
  message: string
}

const navigation: { key: PageKey; label: string; icon: IconName }[] = [
  { key: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { key: 'billing', label: 'New bill', icon: 'billing' },
  { key: 'products', label: 'Products', icon: 'products' },
  { key: 'invoices', label: 'Invoices', icon: 'invoices' },
  { key: 'customers', label: 'Customers', icon: 'customers' },
  { key: 'reports', label: 'Sales reports', icon: 'reports' },
  { key: 'assistant', label: 'AI Assistant', icon: 'assistant' },
]

const pageTitles: Record<PageKey, { title: string; subtitle: string }> = {
  dashboard: { title: 'Dashboard', subtitle: 'A clear view of your shop today.' },
  billing: { title: 'Point of sale', subtitle: 'Create a bill and take payment.' },
  products: { title: 'Products', subtitle: 'Manage your catalog, pricing, and GST.' },
  invoices: { title: 'Invoices', subtitle: 'Find, review, and print completed bills.' },
  customers: { title: 'Customers', subtitle: 'Keep customer details and purchase history together.' },
  reports: { title: 'Sales reports', subtitle: 'Review revenue and top-selling products.' },
  assistant: { title: 'AI Assistant', subtitle: 'Ask grounded questions about your shop.' },
}

function App() {
  const [activePage, setActivePage] = useState<PageKey>('dashboard')
  const [menuOpen, setMenuOpen] = useState(false)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null)
  const [authLoaded, setAuthLoaded] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let active = true
    apiRequest<{ status: string }>('/health')
      .then(() => active && setApiOnline(true))
      .catch(() => active && setApiOnline(false))
    apiRequest<AuthStatus>('/auth/status')
      .then((status) => {
        if (active) {
          setAuthStatus(status)
          setAuthError(null)
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setAuthError(error instanceof Error ? error.message : 'Could not check sign-in status.')
        }
      })
      .finally(() => active && setAuthLoaded(true))
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const requireSignIn = () => {
      setAuthStatus((current) => current && { ...current, authenticated: false })
    }
    window.addEventListener('smartbill-auth-required', requireSignIn)
    return () => window.removeEventListener('smartbill-auth-required', requireSignIn)
  }, [])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 4200)
    return () => window.clearTimeout(timer)
  }, [notice])

  const navigate = (page: PageKey) => {
    setActivePage(page)
    setMenuOpen(false)
  }
  const notify = (kind: NoticeKind, message: string) => setNotice({ kind, message })
  const refreshDashboard = () => setRefreshToken((value) => value + 1)
  const signOut = async () => {
    try {
      await apiRequest<AuthStatus>('/auth/logout', { method: 'POST' })
      setAuthStatus((current) => current && { ...current, authenticated: false })
    } catch (error) {
      notify('error', error instanceof Error ? error.message : 'Could not sign out.')
    }
  }

  if (!authLoaded) {
    return (
      <main className="auth-screen">
        <div className="auth-card"><span className="spinner" /><p>Connecting to SmartBill…</p></div>
      </main>
    )
  }
  if (authError || !authStatus) {
    return (
      <main className="auth-screen">
        <div className="auth-card">
          <div className="brand-mark auth-brand-mark">S</div>
          <h1>SmartBill is unavailable</h1>
          <p className="auth-footnote">{authError ?? 'Could not load sign-in status.'}</p>
        </div>
      </main>
    )
  }
  if (!authStatus.configured || !authStatus.authenticated) {
    return (
      <SignInPage
        configured={authStatus.configured}
        onSignedIn={setAuthStatus}
      />
    )
  }

  return (
    <div className="app-shell">
      {menuOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar${menuOpen ? ' sidebar-open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <strong>SmartBill</strong>
            <span>Retail workspace</span>
          </div>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.key}
              className={`nav-item${activePage === item.key ? ' nav-item-active' : ''}`}
              onClick={() => navigate(item.key)}
              aria-current={activePage === item.key ? 'page' : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.key === 'billing' && <span className="nav-shortcut">F2</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="help-mark">?</div>
          <div><strong>Need a hand?</strong><span>Open any page to get started</span></div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button
            className="icon-button mobile-menu-button"
            aria-label="Open navigation"
            onClick={() => setMenuOpen(true)}
          >
            <Icon name="menu" />
          </button>
          <div className="topbar-heading">
            <span className="topbar-eyebrow">SMARTBILL AI</span>
            <span className="topbar-current">{pageTitles[activePage].title}</span>
          </div>
          <div className="topbar-right">
            <span className={`api-status${apiOnline === false ? ' api-status-offline' : ''}`}>
              <span className="api-status-dot" />
              {apiOnline === null ? 'Connecting' : apiOnline ? 'Backend connected' : 'Backend offline'}
            </span>
            <button className="signout-button" onClick={() => void signOut()}>Sign out</button>
          </div>
        </header>

        <main className="main-content">
          {activePage === 'dashboard' && (
            <DashboardPage refreshToken={refreshToken} onNavigate={navigate} />
          )}
          {activePage === 'billing' && (
            <BillingPage notify={notify} onComplete={refreshDashboard} />
          )}
          {activePage === 'products' && <ProductsPage notify={notify} />}
          {activePage === 'invoices' && <InvoicesPage refreshToken={refreshToken} />}
          {activePage === 'customers' && <CustomersPage notify={notify} />}
          {activePage === 'reports' && <ReportsPage />}
          {activePage === 'assistant' && <AssistantPage />}
        </main>
      </div>

      {notice && (
        <div className={`toast toast-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
          <Icon name={notice.kind === 'success' ? 'check' : 'close'} />
          <span>{notice.message}</span>
          <button className="toast-close" aria-label="Dismiss message" onClick={() => setNotice(null)}>
            <Icon name="close" size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

export default App
