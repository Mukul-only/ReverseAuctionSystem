import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { AuctionStatusBadge } from '../components/auction/AuctionStatusBadge'
import { Countdown } from '../components/auction/Countdown'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { Input } from '../components/ui/Input'
import {
  ApiError,
  cancelAuction,
  closeAuction,
  getAuction,
  listBids,
  placeBid,
  verifyAuction,
  type Auction,
  type Bid,
  type ChainVerification,
} from '../lib/api'
import {
  formatDateTime,
  formatMoney,
  isEnded,
  minorToRupees,
  rupeesToMinor,
} from '../lib/format'

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `bid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function AuctionDetail() {
  const params = useParams()
  const { user } = useAuth()

  const auctionId = Number(params.id)
  const validId = Number.isInteger(auctionId) && auctionId > 0

  const [auction, setAuction] = useState<Auction | null>(null)
  const [bids, setBids] = useState<Bid[]>([])
  const [verification, setVerification] = useState<ChainVerification | null>(
    null,
  )
  const [loading, setLoading] = useState(validId)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const [actionPending, setActionPending] = useState<
    'close' | 'cancel' | null
  >(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [bidAmount, setBidAmount] = useState('')
  const [bidPending, setBidPending] = useState(false)
  const [bidError, setBidError] = useState<string | null>(null)
  const [bidNotice, setBidNotice] = useState<string | null>(null)

  const refreshFeed = useCallback(async () => {
    const [nextAuction, nextBids] = await Promise.all([
      getAuction(auctionId),
      listBids(auctionId),
    ])
    setAuction(nextAuction)
    setBids(nextBids)
  }, [auctionId])

  /*
   * Interim live feed: a 4-second poll while the tab is visible. Milestone 7
   * replaces this with a WebSocket broadcast and keeps polling as fallback.
   */
  useEffect(() => {
    if (!validId) return

    let active = true
    let initial = true

    async function load() {
      if (initial) setLoading(true)
      try {
        const [nextAuction, nextBids] = await Promise.all([
          getAuction(auctionId),
          listBids(auctionId),
        ])
        if (!active) return
        setAuction(nextAuction)
        setBids(nextBids)
        setError(null)
      } catch (cause) {
        if (!active || !initial) return
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
        if (active && initial) {
          setLoading(false)
          initial = false
        }
      }
    }

    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, 4_000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [auctionId, validId, reloadToken])

  // Re-verify whenever the ledger grows or its head changes.
  const headSignature = bids.length > 0 ? bids[bids.length - 1].signature : ''

  useEffect(() => {
    if (!validId) return

    let active = true
    verifyAuction(auctionId)
      .then((result) => {
        if (active) setVerification(result)
      })
      .catch(() => {
        if (active) setVerification(null)
      })

    return () => {
      active = false
    }
  }, [auctionId, validId, bids.length, headSignature])

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
      await refreshFeed()
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

  async function handleBidSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!auction) return

    const minimumAllowed = auction.min_decrement
    const ceiling =
      (auction.lowest_bid ?? auction.starting_price) - minimumAllowed
    const amount = rupeesToMinor(bidAmount)

    if (!Number.isFinite(amount) || amount <= 0) {
      setBidError('Enter a positive amount.')
      return
    }
    if (amount > ceiling) {
      setBidError(
        `Bid must be at most ${formatMoney(ceiling, auction.currency)}.`,
      )
      return
    }

    setBidPending(true)
    setBidError(null)
    setBidNotice(null)
    try {
      await placeBid(auction.id, {
        amount,
        idempotency_key: newIdempotencyKey(),
      })
      setBidAmount('')
      setBidNotice('Bid signed and added to the ledger.')
      await refreshFeed()
    } catch (cause) {
      setBidError(
        cause instanceof ApiError
          ? cause.message
          : 'The bid could not be placed. Try again.',
      )
    } finally {
      setBidPending(false)
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
            <Button
              variant="ghost-sm"
              onClick={() => setReloadToken((value) => value + 1)}
            >
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
  const ceiling = currentPrice - auction.min_decrement
  const canBid =
    user?.role === 'seller' &&
    auction.status === 'open' &&
    !ended &&
    ceiling > 0
  const ledger = [...bids].reverse()
  const winningBid =
    auction.winning_bid_id === null
      ? null
      : (bids.find((bid) => bid.id === auction.winning_bid_id) ?? null)

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
            Posted by {auction.buyer_email} ·{' '}
            {formatDateTime(auction.created_at)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <AuctionStatusBadge status={auction.status} />
          {auction.status === 'open' && <Countdown endsAt={auction.ends_at} />}
        </div>
      </div>

      {winningBid && (
        <Card className="mt-8 border-link/30 bg-link/5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Eyebrow>Awarded</Eyebrow>
              <p className="mt-1 text-body-md text-ink">
                <span className="font-mono">{winningBid.seller_email}</span> won
                at{' '}
                <span className="font-mono">
                  {formatMoney(winningBid.amount, auction.currency)}
                </span>
                .
              </p>
            </div>
            <Badge tone="active">lowest bid</Badge>
          </div>
        </Card>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_0.6fr] lg:items-start">
        <div className="space-y-6">
          <Card>
            <Eyebrow>Requirement</Eyebrow>
            <p className="mt-3 whitespace-pre-line text-body-lg text-body">
              {auction.description || 'No description was provided.'}
            </p>
          </Card>

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Eyebrow>Bid ledger</Eyebrow>
              <div className="flex items-center gap-3">
                <span className="font-mono text-body-sm text-mute">
                  {auction.bid_count} {auction.bid_count === 1 ? 'bid' : 'bids'}
                </span>
                {verification && (
                  <Badge tone={verification.valid ? 'active' : 'danger'}>
                    {verification.valid ? 'chain verified' : 'tamper detected'}
                  </Badge>
                )}
              </div>
            </div>

            {verification && !verification.valid && (
              <p
                role="alert"
                className="mt-3 rounded-sm border border-error/30 bg-error/5 px-3 py-2 text-body-sm text-error"
              >
                {verification.reason} First invalid bid: #
                {verification.first_invalid_bid_id}.
              </p>
            )}

            {ledger.length === 0 ? (
              <div className="mt-4 rounded-sm border border-dashed border-hairline bg-canvas px-4 py-8 text-center">
                <p className="text-body-md text-body">No bids yet.</p>
                <p className="mt-1 text-body-sm text-mute">
                  {auction.status === 'open'
                    ? 'The first signed bid will appear here within a few seconds.'
                    : 'This auction closed without a bid.'}
                </p>
              </div>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="font-mono text-eyebrow uppercase text-mute">
                      <th className="py-2 pr-3 font-medium">Bidder</th>
                      <th className="py-2 pr-3 font-medium">Amount</th>
                      <th className="py-2 pr-3 font-medium">Signature</th>
                      <th className="py-2 font-medium">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.map((bid, index) => (
                      <tr key={bid.id} className="border-t border-hairline">
                        <td className="max-w-[12rem] truncate py-2.5 pr-3 text-body-md text-body">
                          {bid.seller_email}
                          {index === 0 && auction.status === 'open' && (
                            <span className="ml-2 font-mono text-body-sm text-link">
                              lowest
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap py-2.5 pr-3 font-mono text-body-md text-ink">
                          {formatMoney(bid.amount, auction.currency)}
                        </td>
                        <td
                          className="whitespace-nowrap py-2.5 pr-3 font-mono text-body-sm text-mute"
                          title={bid.signature}
                        >
                          {bid.signature.slice(0, 10)}…
                        </td>
                        <td className="whitespace-nowrap py-2.5 font-mono text-body-sm text-mute">
                          {formatDateTime(bid.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {verification && (
              <p className="mt-4 border-t border-hairline pt-3 font-mono text-body-sm text-mute">
                verified {verification.checked}/{verification.bid_count}{' '}
                signatures · HMAC-SHA256 chain
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
              {auction.status === 'open' && ceiling > 0 && (
                <div className="flex items-center justify-between py-2.5">
                  <dt className="text-body-sm text-mute">Max next bid</dt>
                  <dd className="font-mono text-body-md text-ink">
                    {formatMoney(ceiling, auction.currency)}
                  </dd>
                </div>
              )}
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
                    {actionPending === 'close'
                      ? 'Closing...'
                      : 'Close and award'}
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
                <Link
                  to="/login?mode=login"
                  className="text-link hover:underline"
                >
                  Sign in
                </Link>{' '}
                as a seller to place a signed bid.
              </p>
            )}
          </Card>

          {canBid && (
            <Card>
              <Eyebrow>Place a bid</Eyebrow>
              <p className="mt-2 text-body-sm text-body">
                Bid at or below{' '}
                <span className="font-mono text-ink">
                  {formatMoney(ceiling, auction.currency)}
                </span>{' '}
                to beat the current lowest by the minimum decrement.
              </p>
              <form className="mt-4 space-y-3" onSubmit={handleBidSubmit}>
                <div>
                  <label
                    htmlFor="bidAmount"
                    className="mb-1.5 block text-label-sm text-ink"
                  >
                    Your bid (INR)
                  </label>
                  <Input
                    id="bidAmount"
                    inputMode="decimal"
                    value={bidAmount}
                    onChange={(event) => setBidAmount(event.target.value)}
                    placeholder={minorToRupees(ceiling)}
                  />
                </div>
                {bidError && (
                  <p role="alert" className="text-body-sm text-error">
                    {bidError}
                  </p>
                )}
                {bidNotice && (
                  <p role="status" className="text-body-sm text-link">
                    {bidNotice}
                  </p>
                )}
                <Button
                  type="submit"
                  variant="primary-sm"
                  className="w-full"
                  disabled={bidPending}
                >
                  {bidPending ? 'Signing...' : 'Sign and place bid'}
                </Button>
              </form>
              <p className="mt-3 font-mono text-body-sm text-mute">
                HMAC-SHA256 · prev-hash chain · idempotent
              </p>
            </Card>
          )}

          {user?.role === 'seller' && !canBid && (
            <Card>
              <Eyebrow>Bidding</Eyebrow>
              <p className="mt-2 text-body-sm text-body">
                {auction.status === 'open'
                  ? 'This auction has ended. The lowest bid will be awarded.'
                  : 'Bidding is closed for this auction.'}
              </p>
            </Card>
          )}

          {isAdmin && (
            <Card>
              <Eyebrow>Admin note</Eyebrow>
              <p className="mt-2 text-body-sm text-body">
                Admins may cancel an auction but never close, bid, or award it.
                That separation of duties is enforced server-side.
              </p>
            </Card>
          )}
        </div>
      </div>
    </section>
  )
}