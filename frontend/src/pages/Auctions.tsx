import { useNavigate } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'

export function Auctions() {
  const navigate = useNavigate()

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <Eyebrow>Open auctions</Eyebrow>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-heading-lg text-ink">Bidding floor</h1>
        <Button variant="ghost-sm" onClick={() => navigate('/')}>
          Back to overview
        </Button>
      </div>

      <Card className="mt-8 flex flex-col items-start gap-3 p-10">
        <span className="font-mono text-body-sm text-mute">EMPTY</span>
        <h2 className="text-heading-md text-ink">No auctions are live yet.</h2>
        <p className="max-w-md text-body-md text-body">
          Auction creation and descending bids arrive in milestones 5 and 6.
          Until then this floor stays quiet.
        </p>
      </Card>
    </section>
  )
}