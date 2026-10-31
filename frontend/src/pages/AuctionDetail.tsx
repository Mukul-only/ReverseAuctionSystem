import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { AuctionStatusBadge } from '../components/auction/AuctionStatusBadge'
import { Countdown } from '../components/auction/Countdown'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import {
  ApiError,
  cancelAuction,
  closeAuction,
  getAuction,
  type Auction,
} from '../lib/api'
import { formatDateTime, formatMoney, isEnded } from '../lib/format'

export function AuctionDetail() {
  const params = useParams()
  const { user } = useAuth()

  const auctionId = Number(params.id)
  const validId = Number.isInteger(auctionId) && auctionId > 0

  const [auction, setAuction] = useState<Auction | null>(null)
  const [loading, setLoading] = useState(validId)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const [actionPending, setActionPending] = useState<
    'close' | 'cancel' | null
  >(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!validId) return

    let active = true

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await getAuction(auctionId)
        if (active) setAuction(result)
      } catch (cause) {
        if (!active) return
        if (cause instanceof ApiError && cause.status === 404) {
          setError('Auction not found.')
        } else {
          setError(
            cause instanceof ApiError
              ? cause.message
              : 'Could not load this auction.',
          )
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    void load()
    return () => {
      active = false
    }
  }, [auctionId, validId, reloadToken])

  async function runAction(action: 'close' | 'cancel') {
    if (!auction) return
    setActionPending(action)
    setActionError(null)
    try {
      const updated =
        action === 'close'
          ? await closeAuction(auction.id)
          : await cancelAuction(auction.id)
      setAuction(updated)
    } catch (cause) {
      setActionError(
        cause instanceof ApiError
          ? cause.message
          : 'That action could not be completed.',
      )
    } finally {
      setActionPending(null)
    }
  }

  if (loading) {
    return (
      <section className="mx-auto w-full max-w-6xl px-6 py-16">
        <div className="h-8 w-64 animate-pulse rounded-sm bg-hairline-soft" />
        <div className="mt-6 h-64 animate-pulse rounded-md border border-hairline bg-hairline-soft" />
      </section>
    )
  }

  if (error || !auction) {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <Eyebrow>Auction</Eyebrow>
        <Card className="mt-6 flex flex-col items-start gap-3">
          <span className="font-mono text-body-sm text-mute">404</span>
          <h1 className="text-heading-md text-ink">
            {error ?? 'Auction not found.'}
          </h1>
          <p className="text-body-md text-body">
            The auction may have been removed, or the link may be wrong.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost-sm" onClick={() => setReloadToken((v) => v + 1)}>
              Try again
            </Button>
            <Link to="/auctions">
              <Button variant="ghost-sm">Back to auctions</Button>
            </Link>
          </div>
        </Card>
      </section>
    )
  }

  const isOwner = user?.id === auction.buyer_id
  const isAdmin = user?.role === 'admin'
  const ended = isEnded(auction.ends_at)
  const canClose = isOwner && auction.status === 'open' && ended
  const canCancel = (isOwner || isAdmin) && auction.status === 'open'
  const currentPrice = auction.lowest_bid ?? auction.starting_price

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <Link
        to="/auctions"
        className="font-mono text-body-sm text-mute hover:text-ink"
      >
        ← All auctions
      </Link>

      <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <Eyebrow>Auction #{auction.id}</Eyebrow>
          <h1 className="mt-3 max-w-2xl text-balance text-heading-lg text-ink">
            {auction.title}
          </h1>
          <p className="mt-2 text-body-sm text-mute">
            Posted by {auction.buyer_email} · {formatDateTime(auction.created_at)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <AuctionStatusBadge status={auction.status} />
          {auction.status === 'open' && <Countdown endsAt={auction.ends_at} />}
        </div>
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_0.6fr] lg:items-start">
        <div className="space-y-6">
          <Card>
            <Eyebrow>Requirement</Eyebrow>
            <p className="mt-3 whitespace-pre-line text-body-lg text-body">
              {auction.description || 'No description was provided.'}
            </p>
          </Card>

          <Card>
            <div className="flex items-center justify-between gap-3">
              <Eyebrow>Bid ledger</Eyebrow>
              <span className="font-mono text-body-sm text-mute">
                {auction.bid_count} {auction.bid_count === 1 ? 'bid' : 'bids'}
              </span>
            </div>

            {auction.bid_count === 0 ? (
              <div className="mt-4 rounded-sm border border-dashed border-hairline bg-canvas px-4 py-8 text-center">
                <p className="text-body-md text-body">No bids yet.</p>
                <p className="mt-1 text-body-sm text-mute">
                  Signed, hash-chained bids arrive in Milestone 6.
                </p>
              </div>
            ) : (
              <p className="mt-4 text-body-md text-body">
                The lowest bid is currently{' '}
                <span className="font-mono text-ink">
                  {formatMoney(currentPrice, auction.currency)}
                </span>
                .
              </p>
            )}
          </Card>

          <Card>
            <Eyebrow>Timeline</Eyebrow>
            <dl className="mt-3 divide-y divide-hairline border-y border-hairline">
              <div className="flex items-center justify-between py-2.5">
                <dt className="text-body-sm text-mute">Opened</dt>
                <dd className="font-mono text-body-md text-ink">
                  {formatDateTime(auction.starts_at)}
                </dd>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <dt className="text-body-sm text-mute">Closes</dt>
                <dd className="font-mono text-body-md text-ink">
                  {formatDateTime(auction.ends_at)}
                </dd>
              </div>
            </dl>
          </Card>
        </div>

        <div className="space-y-6 lg:sticky lg:top-20">
          <Card>
            <Eyebrow>
              {auction.lowest_bid !== null ? 'Lowest bid' : 'Starting price'}
            </Eyebrow>
            <p className="mt-2 text-heading-lg text-ink">
              {formatMoney(currentPrice, auction.currency)}
            </p>

            <dl className="mt-4 divide-y divide-hairline border-y border-hairline">
              <div className="flex items-center justify-between py-2.5">
                <dt className="text-body-sm text-mute">Starting price</dt>
                <dd className="font-mono text-body-md text-ink">
                  {formatMoney(auction.starting_price, auction.currency)}
                </dd>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <dt className="text-body-sm text-mute">Min. decrement</dt>
                <dd className="font-mono text-body-md text-ink">
                  {formatMoney(auction.min_decrement, auction.currency)}
                </dd>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <dt className="text-body-sm text-mute">Bids</dt>
                <dd className="font-mono text-body-md text-ink">
                  {auction.bid_count}
                </dd>
              </div>
            </dl>

            {auction.status === 'open' && (
              <div className="mt-4 flex items-center justify-between gap-3 rounded-sm bg-canvas px-3 py-2">
                <span className="text-body-sm text-mute">Time left</span>
                <Countdown endsAt={auction.ends_at} />
              </div>
            )}

            {(canClose || canCancel) && (
              <div className="mt-5 flex flex-col gap-2 border-t border-hairline pt-5">
                {canClose && (
                  <Button
                    variant="primary-sm"
                    disabled={actionPending !== null}
                    onClick={() => runAction('close')}
                  >
                    {actionPending === 'close' ? 'Closing...' : 'Close auction'}
                  </Button>
                )}
                {canCancel && (
                  <Button
                    variant="ghost-sm"
                    disabled={actionPending !== null}
                    onClick={() => runAction('cancel')}
                  >
                    {actionPending === 'cancel'
                      ? 'Cancelling...'
                      : 'Cancel auction'}
                  </Button>
                )}
                {actionError && (
                  <p role="alert" className="text-body-sm text-error">
                    {actionError}
                  </p>
                )}
              </div>
            )}

            {!user && (
              <p className="mt-5 border-t border-hairline pt-4 text-body-sm text-mute">
                <Link to="/login?mode=login" className="text-link hover:underline">
                  Sign in
                </Link>{' '}
                as a seller to bid when the ledger opens.
              </p>
            )}
          </Card>

          {isAdmin && (
            <Card>
              <Eyebrow>Admin note</Eyebrow>
              <p className="mt-2 text-body-sm text-body">
                Admins may cancel an auction but never close or award it. That
                separation of duties is enforced server-side.
              </p>
            </Card>
          )}
        </div>
      </div>
    </section>
  )
}