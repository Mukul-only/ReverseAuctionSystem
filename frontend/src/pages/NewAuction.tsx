import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { Input } from '../components/ui/Input'
import { Textarea } from '../components/ui/Textarea'
import { ApiError, createAuction } from '../lib/api'
import { formatMoney, rupeesToMinor } from '../lib/format'

function Field({
  htmlFor,
  label,
  hint,
  children,
}: {
  htmlFor: string
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-label-sm text-ink">
          {label}
        </label>
        {hint && (
          <span className="text-body-sm text-mute">{hint}</span>
        )}
      </div>
      {children}
    </div>
  )
}

export function NewAuction() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [startingPrice, setStartingPrice] = useState('')
  const [minDecrement, setMinDecrement] = useState('')
  const [durationHours, setDurationHours] = useState('48')

  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (loading) {
    return (
      <section className="mx-auto w-full max-w-6xl px-6 py-16">
        <p className="text-body-sm text-mute">checking session...</p>
      </section>
    )
  }

  if (!user) {
    return <Navigate to="/login?mode=login" replace />
  }

  if (user.role !== 'buyer') {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <Eyebrow>Post a requirement</Eyebrow>
        <Card className="mt-6 flex flex-col items-start gap-3">
          <h1 className="text-heading-md text-ink">Buyers post auctions.</h1>
          <p className="text-body-md text-body">
            Your account has the <span>{user.role}</span>{' '}
            role. Sellers compete on auctions; they cannot create them.
          </p>
          <Button variant="ghost-sm" onClick={() => navigate('/auctions')}>
            Back to the floor
          </Button>
        </Card>
      </section>
    )
  }

  const startingMinor = rupeesToMinor(startingPrice)
  const decrementMinor = rupeesToMinor(minDecrement)
  const duration = Number(durationHours)

  function validate(): string | null {
    if (title.trim().length < 3) return 'Title needs at least 3 characters.'
    if (!Number.isFinite(startingMinor) || startingMinor <= 0) {
      return 'Starting price must be a positive amount.'
    }
    if (!Number.isFinite(decrementMinor) || decrementMinor <= 0) {
      return 'Minimum decrement must be a positive amount.'
    }
    if (decrementMinor > startingMinor) {
      return 'Minimum decrement cannot exceed the starting price.'
    }
    if (!Number.isInteger(duration) || duration < 1 || duration > 720) {
      return 'Duration must be a whole number of hours between 1 and 720.'
    }
    return null
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      const auction = await createAuction({
        title: title.trim(),
        description: description.trim(),
        starting_price: startingMinor,
        min_decrement: decrementMinor,
        duration_hours: duration,
      })
      navigate(`/auctions/${auction.id}`)
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'Could not create the auction. Try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <Eyebrow>Post a requirement</Eyebrow>
      <h1 className="mt-3 text-heading-lg text-ink">New auction</h1>
      <p className="mt-2 max-w-lg text-body-md text-body">
        Describe what you need and set the opening price. Sellers will bid
        downward until the clock runs out.
      </p>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_0.6fr] lg:items-start">
        <Card>
          <form className="space-y-6" onSubmit={handleSubmit} noValidate>
            <Field htmlFor="title" label="Title" hint="3–120 characters">
              <Input
                id="title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={120}
                placeholder="Bulk ergonomic chairs for the lab"
              />
            </Field>

            <Field
              htmlFor="description"
              label="Description"
              hint="optional"
            >
              <Textarea
                id="description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={5}
                maxLength={5000}
                placeholder="Quantity, specifications, delivery window, and any constraints."
              />
            </Field>

            <div className="grid gap-5 sm:grid-cols-2">
              <Field htmlFor="startingPrice" label="Starting price" hint="INR">
                <Input
                  id="startingPrice"
                  inputMode="decimal"
                  value={startingPrice}
                  onChange={(event) => setStartingPrice(event.target.value)}
                  placeholder="25000"
                />
              </Field>

              <Field
                htmlFor="minDecrement"
                label="Minimum decrement"
                hint="INR"
              >
                <Input
                  id="minDecrement"
                  inputMode="decimal"
                  value={minDecrement}
                  onChange={(event) => setMinDecrement(event.target.value)}
                  placeholder="250"
                />
              </Field>
            </div>

            <Field htmlFor="durationHours" label="Duration" hint="hours">
              <Input
                id="durationHours"
                inputMode="numeric"
                value={durationHours}
                onChange={(event) => setDurationHours(event.target.value)}
                placeholder="48"
              />
            </Field>

            {error && (
              <p
                role="alert"
                className="rounded-sm border border-error/30 bg-error/5 px-3 py-2 text-body-md text-error"
              >
                {error}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-5">
              <Button type="submit" variant="primary" disabled={submitting}>
                {submitting ? 'Publishing...' : 'Publish auction'}
              </Button>
              <Button
                variant="ghost-sm"
                disabled={submitting}
                onClick={() => navigate('/auctions')}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>

        <Card className="lg:sticky lg:top-20">
          <Eyebrow>Preview</Eyebrow>
          <h2 className="mt-2 text-heading-md text-ink">
            {title.trim() || 'Untitled requirement'}
          </h2>
          <p className="mt-2 line-clamp-3 text-body-md text-body">
            {description.trim() || 'No description yet.'}
          </p>

          <dl className="mt-5 divide-y divide-hairline border-y border-hairline">
            <div className="flex items-center justify-between py-2.5">
              <dt className="text-body-sm text-mute">Opening price</dt>
              <dd className="text-body-md text-ink">
                {startingMinor > 0 ? formatMoney(startingMinor) : '—'}
              </dd>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <dt className="text-body-sm text-mute">Minimum decrement</dt>
              <dd className="text-body-md text-ink">
                {decrementMinor > 0 ? formatMoney(decrementMinor) : '—'}
              </dd>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <dt className="text-body-sm text-mute">Closes in</dt>
              <dd className="text-body-md text-ink">
                {Number.isInteger(duration) && duration > 0
                  ? `${duration} h`
                  : '—'}
              </dd>
            </div>
          </dl>

          <p className="mt-4 text-body-sm text-mute">
            Every mutation requires a CSRF token and is checked against your
            buyer role on the server.
          </p>
        </Card>
      </div>
    </section>
  )
}