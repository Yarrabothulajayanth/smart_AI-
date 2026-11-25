import { useState, type FormEvent } from 'react'
import { apiRequest } from '../api'
import type { AuthStatus } from '../types'

export function SignInPage({
  configured,
  onSignedIn,
}: {
  configured: boolean
  onSignedIn: (status: AuthStatus) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const status = await apiRequest<AuthStatus>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      onSignedIn(status)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <div className="brand-mark auth-brand-mark">S</div>
        <span className="topbar-eyebrow">SMARTBILL AI</span>
        <h1>Owner sign-in</h1>
        {configured ? (
          <form className="form-stack" onSubmit={(event) => void submit(event)}>
            <label className="form-field">
              <span>Username</span>
              <input
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>Password</span>
              <input
                autoComplete="current-password"
                required
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button button-primary auth-submit" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        ) : (
          <div className="notice" role="alert">
            Owner sign-in is not configured. Set
            {' '}<code>SMARTBILL_OWNER_USERNAME</code>,
            {' '}<code>SMARTBILL_OWNER_PASSWORD_HASH</code>, and
            {' '}<code>SMARTBILL_SESSION_SECRET</code> in the backend process
            environment, then restart FastAPI.
          </div>
        )}
        <p className="auth-footnote">Only the configured shop owner can access business records.</p>
      </section>
    </main>
  )
}
