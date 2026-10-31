import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { getHealth, type Health } from '../lib/api'
import { cn } from '../lib/cn'

type MilestoneState = 'done' | 'next' | 'pending'

const MILESTONES: Array<{ id: string; label: string; state: MilestoneState }> = [
  { id: '01', label: 'API + SPA scaffold', state: 'done' },
  { id: '02', label: 'Data layer', state: 'done' },
  { id: '03', label: 'Auth, sessions, CSRF', state: 'next' },
  { id: '04', label: 'RBAC + ownership checks', state: 'pending' },
  { id: '05', label: 'Auction lifecycle', state: 'pending' },
  { id: '06', label: 'Signed bid ledger', state: 'pending' },
]

const FEATURES = [
  {
    index: '01',
    title: 'Signed bids',
    body: 'Each bid carries an HMAC signature and a link to the previous bid, so the ledger cannot be edited silently.',
  },
  {
    index: '02',
    title: 'Hash-chained audit',
    body: 'Logins, bids, and admin actions append to an HMAC chain that an admin can verify at any time.',
  },
  {
    index: '03',
    title: 'Least privilege',
    body: 'Buyers, sellers, and admins each get only the actions their role allows — enforced server-side.',
  },
]

const DOT_CLASSES: Record<MilestoneState, string> = {
  done: 'bg-link',
  next: 'bg-warning',
  pending: 'bg-hairline',
}

export function Landing() {
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let active = true
    getHealth()
      .then((result) => {
        if (active) setHealth(result)
      })
      .catch(() => {
        if (active) setOffline(true)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <>
      <section className="relative isolate overflow-hidden border-b border-hairline">
        <div className="mesh-gradient" aria-hidden="true" />

        <div className="mx-auto grid w-full max-w-6xl gap-12 px-6 py-20 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:py-28">
          <div>
            <Eyebrow>Reverse auction protocol</Eyebrow>
            <h1 className="mt-4 max-w-xl text-balance text-display-xl text-ink">
              The lowest bid wins.
            </h1>
            <p className="mt-5 max-w-lg text-body-lg text-body">
              Buyers post a requirement. Sellers compete downward in real time.
              Every bid is signed, chained, and auditable.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button variant="primary" onClick={() => navigate('/auctions')}>
                Enter the auction
              </Button>
              <Button variant="secondary" onClick={() => navigate('/security')}>
                Read the security model
              </Button>
            </div>
            <p className="mt-6 font-mono text-body-sm text-mute">
              argon2id · server sessions · hmac-sha256 ledger
            </p>
          </div>

          <Card elevated className="relative">
            <div className="flex items-start justify-between gap-4">
              <div>
                <Eyebrow>System status</Eyebrow>
                <h2 className="mt-2 text-heading-md text-ink">Scaffold online</h2>
              </div>
              <Badge tone={offline ? 'danger' : health ? 'active' : 'neutral'}>
                {offline ? 'API offline' : health ? 'API healthy' : 'Checking'}
              </Badge>
            </div>

            <div className="mt-5 rounded-sm border border-hairline bg-canvas px-4 py-3">
              <div className="flex items-center justify-between gap-3 font-mono text-body-sm">
                <span className="text-mute">GET /api/health</span>
                <span className="text-ink">
                  {offline ? 'unreachable' : health ? '200 OK' : 'waiting'}
                </span>
              </div>
              <p className="mt-1 truncate font-mono text-body-sm text-mute">
                {health ? `${health.service} · ${health.env}` : 'no response yet'}
              </p>
            </div>

            <ul className="mt-6 divide-y divide-hairline border-y border-hairline">
              {MILESTONES.map((milestone) => (
                <li
                  key={milestone.id}
                  className="flex items-center gap-3 py-2.5"
                >
                  <span
                    className={cn(
                      'size-1.5 rounded-full',
                      DOT_CLASSES[milestone.state],
                    )}
                    aria-hidden="true"
                  />
                  <span className="font-mono text-body-sm text-mute">
                    {milestone.id}
                  </span>
                  <span className="text-body-md text-body">{milestone.label}</span>
                  <span className="ml-auto font-mono text-body-sm text-mute">
                    {milestone.state}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </section>

      <section className="border-b border-hairline">
        <div className="mx-auto w-full max-w-6xl px-6 py-16">
          <Eyebrow>Security model</Eyebrow>
          <h2 className="mt-3 text-heading-lg text-ink">
            Built like an audit trail.
          </h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {FEATURES.map((feature) => (
              <Card key={feature.index}>
                <span className="font-mono text-body-sm text-mute">
                  {feature.index}
                </span>
                <h3 className="mt-3 text-heading-md text-ink">{feature.title}</h3>
                <p className="mt-2 text-body-md text-body">{feature.body}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}