import { Link } from 'react-router-dom'
import type { Auction } from '../../lib/api'
import { formatMoney } from '../../lib/format'
import { Card } from '../ui/Card'
import { AuctionStatusBadge } from './AuctionStatusBadge'
import { Countdown } from './Countdown'

export function AuctionCard({ auction }: { auction: Auction }) {
  const hasBids = auction.lowest_bid !== null
  const headlinePrice = auction.lowest_bid ?? auction.starting_price

  return (
    <Card className="flex h-full flex-col p-0 transition-colors hover:border-faint">
      <Link
        to={`/auctions/${auction.id}`}
        className="flex h-full flex-col gap-4 p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-heading-md text-ink">{auction.title}</h3>
          <AuctionStatusBadge status={auction.status} />
        </div>

        <p className="line-clamp-2 text-body-md text-body">
          {auction.description || 'No description provided.'}
        </p>

        <div className="mt-auto grid grid-cols-2 gap-4 border-t border-hairline pt-4">
          <div>
            <p className="text-eyebrow uppercase text-mute">
              {hasBids ? 'Lowest bid' : 'Starting price'}
            </p>
            <p className="mt-1 text-heading-md text-ink">
              {formatMoney(headlinePrice, auction.currency)}
            </p>
          </div>
          <div>
            <p className="text-eyebrow uppercase text-mute">Bids</p>
            <p className="mt-1 text-heading-md text-ink">{auction.bid_count}</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 text-body-sm text-mute">
          <span className="truncate">by {auction.buyer_email}</span>
          {auction.status === 'open' ? (
            <Countdown endsAt={auction.ends_at} />
          ) : (
            <span>{auction.status}</span>
          )}
        </div>
      </Link>
    </Card>
  )
}