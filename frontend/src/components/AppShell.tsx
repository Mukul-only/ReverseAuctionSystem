import type { ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { cn } from '../lib/cn'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'

const NAV_ITEMS = [
  { to: '/auctions', label: 'Auctions' },
  { to: '/security', label: 'Security' },
]

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, signOut } = useAuth()
  const navigate = useNavigate()

  async function handleSignOut() {
    await signOut()
    navigate('/')
  }

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
            {user && (
              <NavLink
                to="/account/security"
                className={({ isActive }) =>
                  cn(
                    'rounded-full px-3 py-2 text-body-md transition-colors',
                    isActive ? 'text-ink' : 'text-body hover:bg-hairline-soft',
                  )
                }
              >
                Account
              </NavLink>
            )}
            {user?.role === 'admin' && (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  cn(
                    'rounded-full px-3 py-2 text-body-md transition-colors',
                    isActive ? 'text-ink' : 'text-body hover:bg-hairline-soft',
                  )
                }
              >
                Admin
              </NavLink>
            )}
          </nav>

          <div className="flex items-center gap-2">
            {loading ? (
              <span className="hidden font-mono text-body-sm text-mute sm:inline">
                checking…
              </span>
            ) : user ? (
              <>
                <Badge tone="active" className="hidden sm:inline-flex">
                  {user.role}
                </Badge>
                <span className="hidden max-w-[14rem] truncate text-body-sm text-body md:inline">
                  {user.email}
                </span>
                {user.role === 'buyer' && (
                  <Button
                    variant="primary-sm"
                    onClick={() => navigate('/auctions/new')}
                  >
                    New auction
                  </Button>
                )}
                <Button variant="ghost-sm" onClick={handleSignOut}>
                  Log out
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="ghost-sm"
                  onClick={() => navigate('/login?mode=login')}
                >
                  Log in
                </Button>
                <Button
                  variant="primary-sm"
                  onClick={() => navigate('/login?mode=register')}
                >
                  Sign up
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-hairline">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-6 py-8 text-body-sm text-mute sm:flex-row sm:items-center sm:justify-between">
          <span>Reverse Auction System — MCA project</span>
          <span className="font-mono">build 0.8.0 · milestone 8</span>
        </div>
      </footer>
    </div>
  )
}