import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { Input } from '../components/ui/Input'
import {
  ApiError,
  disableMfa,
  setupMfa,
  verifyMfa,
  type MfaSetup,
} from '../lib/api'

export function AccountSecurity() {
  const { user, refresh } = useAuth()

  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [pending, setPending] = useState<MfaSetup | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!user) {
    return (
      <section className="mx-auto w-full max-w-2xl px-6 py-16">
        <Card className="flex flex-col items-start gap-3 p-10">
          <span className="text-body-sm text-mute">AUTH REQUIRED</span>
          <h1 className="text-heading-md text-ink">Sign in to manage security.</h1>
          <Link to="/login" className="text-body-md text-link hover:underline">
            Go to sign in
          </Link>
        </Card>
      </section>
    )
  }

  function reportError(cause: unknown) {
    setError(
      cause instanceof ApiError ? cause.message : 'Something went wrong.',
    )
  }

  async function beginEnrolment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      const result = await setupMfa(password)
      setPending(result)
      setCode('')
    } catch (cause) {
      reportError(cause)
    } finally {
      setBusy(false)
    }
  }

  async function confirmEnrolment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await verifyMfa(password, code.trim())
      await refresh()
      setPending(null)
      setPassword('')
      setCode('')
      setNotice('Two-factor authentication is now enabled.')
    } catch (cause) {
      reportError(cause)
    } finally {
      setBusy(false)
    }
  }

  async function turnOff(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      await disableMfa(password, code.trim())
      await refresh()
      setPassword('')
      setCode('')
      setNotice('Two-factor authentication was disabled.')
    } catch (cause) {
      reportError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mx-auto w-full max-w-3xl px-6 py-16">
      <Eyebrow>Account security</Eyebrow>
      <h1 className="mt-3 text-heading-lg text-ink">Two-factor authentication</h1>
      <p className="mt-2 max-w-xl text-body-md text-body">
        Protect your account with a time-based one-time password (TOTP) from any
        authenticator app. Administrators must enable it before using the
        console.
      </p>

      <div className="mt-6 flex items-center gap-3">
        <Badge tone={user.totp_enabled ? 'active' : 'warning'}>
          {user.totp_enabled ? 'TOTP enabled' : 'TOTP not enabled'}
        </Badge>
        <span className="text-body-sm text-mute">
          {user.email} · {user.role}
        </span>
      </div>

      {notice && (
        <p
          role="status"
          className="mt-6 rounded-sm border border-link/30 bg-link/5 px-3 py-2 text-body-md text-body"
        >
          {notice}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mt-6 rounded-sm border border-error/30 bg-error/5 px-3 py-2 text-body-md text-error"
        >
          {error}
        </p>
      )}

      {user.totp_enabled ? (
        <Card className="mt-6">
          <h2 className="text-heading-md text-ink">Turn off two-factor</h2>
          <p className="mt-1 max-w-lg text-body-md text-body">
            Confirm your password and a current code. Disabling the factor
            requires both, so a stolen session cannot remove it.
          </p>
          <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={turnOff}>
            <div>
              <label htmlFor="off-password" className="mb-1.5 block text-label-sm text-ink">
                Password
              </label>
              <Input
                id="off-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="off-code" className="mb-1.5 block text-label-sm text-ink">
                Current code
              </label>
              <Input
                id="off-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={8}
                required
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                className="tracking-[0.3em]"
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                type="submit"
                variant="secondary"
                disabled={busy || code.length < 6}
              >
                {busy ? 'Working...' : 'Disable two-factor'}
              </Button>
            </div>
          </form>
        </Card>
      ) : pending ? (
        <Card className="mt-6">
          <h2 className="text-heading-md text-ink">Scan and confirm</h2>
          <p className="mt-1 max-w-lg text-body-md text-body">
            Add this secret to your authenticator app, then enter the current
            code to finish. The secret is stored encrypted at rest.
          </p>
          <div className="mt-4 rounded-sm border border-hairline bg-canvas p-4">
            <span className="block text-body-sm text-mute">SECRET</span>
            <code className="mt-1 block break-all text-body-md text-ink">
              {pending.secret}
            </code>
            <span className="mt-3 block text-body-sm text-mute">
              OTPAUTH URI
            </span>
            <code className="mt-1 block break-all text-body-sm text-body">
              {pending.otpauth_uri}
            </code>
          </div>
          <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={confirmEnrolment}>
            <div>
              <label htmlFor="on-password" className="mb-1.5 block text-label-sm text-ink">
                Password
              </label>
              <Input
                id="on-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="on-code" className="mb-1.5 block text-label-sm text-ink">
                Current code
              </label>
              <Input
                id="on-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={8}
                required
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                className="tracking-[0.3em]"
                placeholder="123456"
              />
            </div>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" variant="primary" disabled={busy || code.length < 6}>
                {busy ? 'Verifying...' : 'Enable two-factor'}
              </Button>
              <Button
                type="button"
                variant="ghost-sm"
                onClick={() => {
                  setPending(null)
                  setPassword('')
                  setCode('')
                  setError(null)
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      ) : (
        <Card className="mt-6">
          <h2 className="text-heading-md text-ink">Enable two-factor</h2>
          <p className="mt-1 max-w-lg text-body-md text-body">
            Re-enter your password to start enrolment. You will be shown a
            secret to add to your authenticator app.
          </p>
          <form className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={beginEnrolment}>
            <div className="flex-1">
              <label htmlFor="start-password" className="mb-1.5 block text-label-sm text-ink">
                Password
              </label>
              <Input
                id="start-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? 'Working...' : 'Start enrolment'}
            </Button>
          </form>
        </Card>
      )}

      {user.role === 'admin' && (
        <p className="mt-6 text-body-sm text-mute">
          Administrator tools require this factor.{' '}
          <Link to="/admin" className="text-link hover:underline">
            Open the console
          </Link>
        </p>
      )}
    </section>
  )
}