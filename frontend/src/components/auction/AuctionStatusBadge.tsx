import type { AuctionStatus } from '../../lib/api'
import { Badge, type BadgeTone } from '../ui/Badge'

const TONES: Record<AuctionStatus, BadgeTone> = {
  draft: 'neutral',
  open: 'active',
  closed: 'warning',
  awarded: 'active',
  cancelled: 'danger',
}

export function AuctionStatusBadge({ status }: { status: AuctionStatus }) {
  return <Badge tone={TONES[status]}>{status}</Badge>
}