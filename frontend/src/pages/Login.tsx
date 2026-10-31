import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { Input } from '../components/ui/Input'

type Mode = 'login' | 'register'
type SignupRole = 'buyer' | 'seller'

const ROLE_OPTIONS: Array<{ value: SignupRole; label: string; hint: string }> = [
  { value: 'buyer', label: 'Buyer', hint: 'Post requirements' },
  { value: 'seller', label: 'Seller', hint: 'Bid downward' },
]

const GUARANTEES = [
  'Argon2id password hashing',
  'Rotating server-side sessions',
  'CSRF-bound state changes',
  'TOTP for administrators',
]

export function Login() {
  const [params, setParams] = useSearchParams()
  const mode: Mode = params.get('mode') === 'register' ? 'register' : 'login'

  const { user, loading, signIn, completeMfa, signUp } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<SignupRole>('buyer')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Second step: a signed challenge plus the one-time code.
  const [challenge, setChallenge] = useState<string | null>(null)
  const [code, setCode] = useState('')

  useEffect(() => {
    if (!loading && user) {
      navigate('/auctions', { replace: true })
    }
  }, [loading, user, navigate])

  function switchMode(next: Mode) {
    setError(null)
    setParams(next === 'login' ? {} : { mode: 'register' }, { replace: true })
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      if (mode === 'register') {
        await signUp(email, password, role)
        navigate('/auctions', { replace: true })
        return
      }

      const result = await signIn(email, password)
      if (result.mfaRequired) {
        setChallenge(result.challenge)
        setCode('')
        return
      }
      navigate('/auctions', { replace: true })
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'Something went wrong. Try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleMfaSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!challenge) return
    setError(null)
    setSubmitting(true)

    try {
      await completeMfa(challenge, code.trim())
      navigate('/auctions', { replace: true })
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'Verification failed. Try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const isRegister = mode === 'register'

  return (
    <section className="grid lg:min-h-[calc(100dvh-3.5rem)] lg:grid-cols-[1.05fr_0.95fr]">
      <div className="relative isolate overflow-hidden border-b border-hairline lg:border-r lg:border-b-0">
        <div className="mesh-gradient" aria-hidden="true" />
        <div className="relative flex h-full flex-col justify-center px-6 py-16 lg:px-12 lg:py-24">
          <Eyebrow>Access portal</Eyebrow>
          <h1 className="mt-4 max-w-md text-balance text-display-xl text-ink">
            Bid with confidence.
          </h1>
          <p className="mt-5 max-w-md text-body-lg text-body">
            One account for posting requirements, placing signed bids, and
            trusting the ledger.
          </p>

          <ul className="mt-8 space-y-3">
            {GUARANTEES.map((item) => (
              <li key={item} className="flex items-center gap-3 text-body-md text-body">
                <span className="size-1.5 rounded-full bg-link" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex items-center justify-center px-6 py-16 lg:py-24">
        <Card elevated className="w-full max-w-md p-8">
          {challenge ? (
            <>
              <div className="mt-2">
                <Eyebrow>Second factor</Eyebrow>
                <h2 className="mt-2 text-heading-md text-ink">
                  Enter your authenticator code
                </h2>
                <p className="mt-1 text-body-sm text-mute">
                  Open your authenticator app and enter the current 6-digit
                  code for {email}.
                </p>
              </div>

              <form
                className="mt-6 space-y-4"
                onSubmit={handleMfaSubmit}
                noValidate
              >
                <div>
                  <label
                    htmlFor="totp"
                    className="mb-1.5 block text-label-sm text-ink"
                  >
                    Authentication code
                  </label>
                  <Input
                    id="totp"
                    name="totp"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={8}
                    autoFocus
                    required
                    value={code}
                    onChange={(event) =>
                      setCode(event.target.value.replace(/\D/g, ''))
                    }
                    placeholder="123456"
                    className="font-mono tracking-[0.3em]"
                  />
                </div>

                {error && (
                  <p
                    role="alert"
                    className="rounded-sm border border-error/30 bg-error/5 px-3 py-2 text-body-md text-error"
                  >
                    {error}
                  </p>
                )}

                <Button
                  type="submit"
                  variant="primary"
                  className="w-full"
                  disabled={submitting || code.length < 6}
                >
                  {submitting ? 'Verifying...' : 'Verify and sign in'}
                </Button>

                <Button
                  type="button"
                  variant="ghost-sm"
                  className="w-full"
                  onClick={() => {
                    setChallenge(null)
                    setError(null)
                    setCode('')
                  }}
                >
                  Back to password
                </Button>
              </form>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-1 rounded-full border border-hairline bg-canvas p-1">
                {(['login', 'register'] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => switchMode(item)}
                    className={cn(
                      'h-8 rounded-full text-btn-md transition-colors',
                      mode === item
                        ? 'bg-elevated text-ink shadow-whisper'
                        : 'text-mute hover:text-body',
                    )}
                  >
                    {item === 'login' ? 'Sign in' : 'Create account'}
                  </button>
                ))}
              </div>

              <div className="mt-6">
                <Eyebrow>{isRegister ? 'New account' : 'Welcome back'}</Eyebrow>
                <h2 className="mt-2 text-heading-md text-ink">
                  {isRegister ? 'Create your account' : 'Sign in to continue'}
                </h2>
                <p className="mt-1 text-body-sm text-mute">
                  Demo password for seeded accounts: DemoPass!234
                </p>
              </div>

              <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
                <div>
                  <label htmlFor="email" className="mb-1.5 block text-label-sm text-ink">
                    Email
                  </label>
                  <Input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                  />
                </div>

                <div>
                  <label
                    htmlFor="password"
                    className="mb-1.5 block text-label-sm text-ink"
                  >
                    Password
                  </label>
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    autoComplete={isRegister ? 'new-password' : 'current-password'}
                    required
                    minLength={isRegister ? 12 : 1}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={isRegister ? 'At least 12 characters' : 'Your password'}
                  />
                </div>

                {isRegister && (
                  <fieldset>
                    <legend className="mb-1.5 text-label-sm text-ink">I am a</legend>
                    <div className="grid grid-cols-2 gap-2">
                      {ROLE_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          aria-pressed={role === option.value}
                          onClick={() => setRole(option.value)}
                          className={cn(
                            'rounded-sm border px-3 py-2 text-left transition-colors',
                            role === option.value
                              ? 'border-ink bg-canvas'
                              : 'border-hairline bg-elevated hover:bg-hairline-soft',
                          )}
                        >
                          <span className="block text-label-sm text-ink">
                            {option.label}
                          </span>
                          <span className="mt-0.5 block text-body-sm text-mute">
                            {option.hint}
                          </span>
                        </button>
                      ))}
                    </div>
                  </fieldset>
                )}

                {error && (
                  <p
                    role="alert"
                    className="rounded-sm border border-error/30 bg-error/5 px-3 py-2 text-body-md text-error"
                  >
                    {error}
                  </p>
                )}

                <Button
                  type="submit"
                  variant="primary"
                  className="w-full"
                  disabled={submitting || loading}
                >
                  {submitting
                    ? 'Working...'
                    : isRegister
                      ? 'Create account'
                      : 'Sign in'}
                </Button>
              </form>

              <p className="mt-5 font-mono text-body-sm text-mute">
                sessions expire after 30 minutes idle
              </p>
            </>
          )}
        </Card>
      </div>
    </section>
  )
}