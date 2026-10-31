import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { cn } from '../lib/cn'

const NAV_ITEMS = [
  { to: '/auctions', label: 'Auctions' },
  { to: '/security', label: 'Security' },
]

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="sticky top-0 z-40 border-b border-hairline bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="grid size-6 place-items-center rounded-sm bg-primary font-mono text-[11px] text-on-primary">
              RA
            </span>
            <span className="text-label-sm text-ink">REVAUCTION</span>
          </Link>

          <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-full px-3 py-2 text-body-md transition-colors',
                    isActive ? 'text-ink' : 'text-body hover:bg-hairline-soft',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <Badge tone="active" className="hidden sm:inline-flex">
              Scaffold
            </Badge>
            <Button variant="ghost-sm">Log in</Button>
            <Button variant="primary-sm">Sign up</Button>
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-hairline">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-6 py-8 text-body-sm text-mute sm:flex-row sm:items-center sm:justify-between">
          <span>Reverse Auction System — MCA project</span>
          <span className="font-mono">build 0.1.0 · milestone 1</span>
        </div>
      </footer>
    </div>
  )
}