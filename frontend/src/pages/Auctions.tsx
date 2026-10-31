import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { AuctionCard } from '../components/auction/AuctionCard'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import {
  ApiError,
  listAuctions,
  listMyAuctions,
  type Auction,
} from '../lib/api'
import { cn } from '../lib/cn'

type Tab = 'open' | 'mine'

export function Auctions() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [tab, setTab] = useState<Tab>('open')
  const [auctions, setAuctions] = useState<Auction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const isBuyer = user?.role === 'buyer'
  // Logging out while on "Mine" falls back to the public floor.
  const shownTab: Tab = user ? tab : 'open'

  useEffect(() => {
    let active = true

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result =
          shownTab === 'mine' ? await listMyAuctions() : await listAuctions()
        if (active) setAuctions(result)
      } catch (cause) {
        if (active) {
          setError(
            cause instanceof ApiError
              ? cause.message
              : 'Could not load auctions.',
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
  }, [shownTab, reloadToken])

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow>Bidding floor</Eyebrow>
          <h1 className="mt-3 text-heading-lg text-ink">Open auctions</h1>
          <p className="mt-2 max-w-lg text-body-md text-body">
            Buyers post requirements; sellers compete downward. The lowest
            valid bid wins when the clock runs out.
          </p>
        </div>
        {isBuyer && (
          <Button variant="primary-sm" onClick={() => navigate('/auctions/new')}>
            New auction
          </Button>
        )}
      </div>

      {user && (
        <div className="mt-8 flex items-center gap-1 rounded-sm border border-hairline bg-elevated p-1">
          {(
            [
              { id: 'open', label: 'Open' },
              { id: 'mine', label: 'Mine' },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              aria-pressed={shownTab === item.id}
              className={cn(
                'h-8 rounded-sm px-3 text-btn-md transition-colors',
                shownTab === item.id
                  ? 'bg-canvas text-ink shadow-whisper'
                  : 'text-mute hover:text-body',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6">
        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <div
                key={index}
                className="h-56 animate-pulse rounded-md border border-hairline bg-hairline-soft"
              />
            ))}
          </div>
        ) : error ? (
          <Card className="flex flex-col items-start gap-3">
            <span className="text-body-sm text-error">ERROR</span>
            <h2 className="text-heading-md text-ink">Could not load auctions.</h2>
            <p className="text-body-md text-body">{error}</p>
            <Button
              variant="ghost-sm"
              onClick={() => setReloadToken((value) => value + 1)}
            >
              Try again
            </Button>
          </Card>
        ) : auctions.length === 0 ? (
          <Card className="flex flex-col items-start gap-3 p-10">
            <span className="text-body-sm text-mute">EMPTY</span>
            <h2 className="text-heading-md text-ink">
              {shownTab === 'mine'
                ? 'You have not posted an auction yet.'
                : 'No auctions are live right now.'}
            </h2>
            <p className="max-w-md text-body-md text-body">
              {shownTab === 'mine'
                ? 'Post a requirement with a starting price and a minimum decrement, then watch sellers compete downward.'
                : 'When a buyer posts a requirement it appears here, publicly and in real time.'}
            </p>
            {isBuyer && (
              <Button
                variant="primary-sm"
                onClick={() => navigate('/auctions/new')}
              >
                Post an auction
              </Button>
            )}
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {auctions.map((auction) => (
              <AuctionCard key={auction.id} auction={auction} />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}