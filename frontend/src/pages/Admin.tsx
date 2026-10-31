import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'
import { Input } from '../components/ui/Input'
import {
  ApiError,
  changeUserRole,
  getAuditAnchor,
  listAdminUsers,
  listAuditEvents,
  listSecurityEvents,
  revokeUserSessions,
  unlockUser,
  verifyAuditChain,
  type AdminUser,
  type AuditAnchor,
  type AuditEvent,
  type AuditVerifyReport,
  type Role,
} from '../lib/api'
import { cn } from '../lib/cn'
import { formatDateTime } from '../lib/format'

type Tab = 'users' | 'audit' | 'security'

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'users', label: 'Users' },
  { id: 'audit', label: 'Audit ledger' },
  { id: 'security', label: 'Security events' },
]

const ROLES: Role[] = ['buyer', 'seller', 'admin']

function messageOf(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : 'Something went wrong.'
}

function MfaNotice() {
  return (
    <p className="mt-4 rounded-sm border border-warning/30 bg-warning/5 px-3 py-2 text-body-md text-body">
      Two-factor authentication must be enabled before using administrator
      tools.{' '}
      <Link to="/account/security" className="text-link hover:underline">
        Enable it now
      </Link>
      .
    </p>
  )
}

/* ------------------------------------------------------------------ */
/* Users                                                               */
/* ------------------------------------------------------------------ */

function UsersPanel() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [needsMfa, setNeedsMfa] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let active = true
    listAdminUsers(query)
      .then((result) => {
        if (!active) return
        setUsers(result)
        setError(null)
        setNeedsMfa(false)
      })
      .catch((cause) => {
        if (!active) return
        setError(messageOf(cause))
        setNeedsMfa(cause instanceof ApiError && cause.status === 403)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [query, reloadToken])

  async function run(action: () => Promise<unknown>, message: string) {
    setError(null)
    setNotice(null)
    try {
      await action()
      setNotice(message)
      setReloadToken((value) => value + 1)
    } catch (cause) {
      setError(messageOf(cause))
    }
  }

  return (
    <div>
      <form
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
        onSubmit={(event) => {
          event.preventDefault()
          setReloadToken((value) => value + 1)
        }}
      >
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by email"
          aria-label="Filter users by email"
          className="sm:max-w-xs"
        />
        <Button type="submit" variant="ghost-sm">
          Filter
        </Button>
      </form>

      {needsMfa && <MfaNotice />}
      {notice && (
        <p role="status" className="mt-4 text-body-md text-body">
          {notice}
        </p>
      )}
      {error && !needsMfa && (
        <p role="alert" className="mt-4 text-body-md text-error">
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-6 text-body-sm text-mute">LOADING...</p>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-md border border-hairline">
          <table className="w-full min-w-[48rem] text-left text-body-md">
            <thead className="border-b border-hairline bg-canvas text-label-sm text-mute">
              <tr>
                <th className="px-4 py-3 font-normal">Email</th>
                <th className="px-4 py-3 font-normal">Role</th>
                <th className="px-4 py-3 font-normal">2FA</th>
                <th className="px-4 py-3 font-normal">Sessions</th>
                <th className="px-4 py-3 font-normal">State</th>
                <th className="px-4 py-3 font-normal">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((row) => {
                const locked = row.locked_until !== null
                return (
                  <tr key={row.id} className="border-b border-hairline last:border-0">
                    <td className="px-4 py-3 text-ink">{row.email}</td>
                    <td className="px-4 py-3">
                      <select
                        aria-label={`Role for ${row.email}`}
                        value={row.role}
                        onChange={(event) =>
                          void run(
                            () =>
                              changeUserRole(row.id, event.target.value as Role),
                            `Role updated for ${row.email}.`,
                          )
                        }
                        className="h-8 rounded-sm border border-hairline bg-elevated px-2 text-body-sm text-ink"
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={row.totp_enabled ? 'active' : 'warning'}>
                        {row.totp_enabled ? 'on' : 'off'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-body-sm text-body">
                      {row.active_sessions}
                    </td>
                    <td className="px-4 py-3">
                      {locked ? (
                        <Badge tone="danger">locked</Badge>
                      ) : (
                        <Badge tone="neutral">active</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="ghost-sm"
                          onClick={() =>
                            void run(
                              () => unlockUser(row.id),
                              `Unlocked ${row.email}.`,
                            )
                          }
                        >
                          Unlock
                        </Button>
                        <Button
                          variant="ghost-sm"
                          onClick={() =>
                            void run(
                              () => revokeUserSessions(row.id),
                              `Revoked sessions for ${row.email}.`,
                            )
                          }
                        >
                          Revoke
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Ledger                                                              */
/* ------------------------------------------------------------------ */

function EventTable({ events }: { events: AuditEvent[] }) {
  return (
    <div className="mt-4 overflow-x-auto rounded-md border border-hairline">
      <table className="w-full min-w-[52rem] text-left text-body-md">
        <thead className="border-b border-hairline bg-canvas text-label-sm text-mute">
          <tr>
            <th className="px-4 py-3 font-normal">Seq</th>
            <th className="px-4 py-3 font-normal">When</th>
            <th className="px-4 py-3 font-normal">Action</th>
            <th className="px-4 py-3 font-normal">Actor</th>
            <th className="px-4 py-3 font-normal">Entity</th>
            <th className="px-4 py-3 font-normal">Hash</th>
          </tr>
        </thead>
        <tbody>
          {events.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-4 py-6 text-mute">
                No events yet.
              </td>
            </tr>
          ) : (
            events.map((event) => (
              <tr key={event.seq} className="border-b border-hairline last:border-0">
                <td className="px-4 py-3 text-body-sm text-mute">
                  {event.seq}
                </td>
                <td className="px-4 py-3 text-body-sm text-body">
                  {formatDateTime(event.created_at)}
                </td>
                <td className="px-4 py-3 text-body-sm text-ink">
                  {event.action}
                </td>
                <td className="px-4 py-3 text-body-sm text-body">
                  {event.actor_email ?? 'system'}
                </td>
                <td className="px-4 py-3 text-body-sm text-body">
                  {event.entity_type
                    ? `${event.entity_type}:${event.entity_id ?? '—'}`
                    : '—'}
                </td>
                <td
                  className="px-4 py-3 text-body-sm text-mute"
                  title={event.hash}
                >
                  {event.hash.slice(0, 12)}…
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function AuditPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [report, setReport] = useState<AuditVerifyReport | null>(null)
  const [anchor, setAnchor] = useState<AuditAnchor | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [needsMfa, setNeedsMfa] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let active = true
    listAuditEvents(100)
      .then((result) => {
        if (!active) return
        setEvents(result)
        setError(null)
      })
      .catch((cause) => {
        if (!active) return
        setError(messageOf(cause))
        setNeedsMfa(cause instanceof ApiError && cause.status === 403)
      })
    return () => {
      active = false
    }
  }, [reloadToken])

  async function verify() {
    setBusy(true)
    try {
      setReport(await verifyAuditChain())
      setEvents(await listAuditEvents(100))
      setError(null)
    } catch (cause) {
      setError(messageOf(cause))
    } finally {
      setBusy(false)
    }
  }

  async function anchorHead() {
    setBusy(true)
    try {
      setAnchor(await getAuditAnchor())
      setError(null)
    } catch (cause) {
      setError(messageOf(cause))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary-sm" onClick={() => void verify()} disabled={busy}>
          Verify chain
        </Button>
        <Button variant="ghost-sm" onClick={() => void anchorHead()} disabled={busy}>
          Signed anchor
        </Button>
        <Button
          variant="ghost-sm"
          onClick={() => setReloadToken((value) => value + 1)}
          disabled={busy}
        >
          Refresh
        </Button>
      </div>

      {needsMfa && <MfaNotice />}
      {error && !needsMfa && (
        <p role="alert" className="mt-4 text-body-md text-error">
          {error}
        </p>
      )}

      {report && (
        <Card className="mt-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={report.valid ? 'active' : 'danger'}>
              {report.valid ? 'chain intact' : 'tamper detected'}
            </Badge>
            <span className="text-body-sm text-mute">
              {report.checked}/{report.event_count} events signed
            </span>
            {report.head_seq !== null && (
              <span className="text-body-sm text-mute">
                head #{report.head_seq}
              </span>
            )}
          </div>
          {report.reason && (
            <p className="mt-2 text-body-md text-error">{report.reason}</p>
          )}
        </Card>
      )}

      {anchor && (
        <Card className="mt-4">
          <span className="text-body-sm text-mute">SIGNED HEAD</span>
          <code className="mt-2 block break-all text-body-sm text-body">
            seq={anchor.seq} count={anchor.event_count}
            <br />
            {anchor.signature}
          </code>
          <p className="mt-2 text-body-sm text-mute">
            Store this off-system to detect truncation later.
          </p>
        </Card>
      )}

      <EventTable events={events} />
    </div>
  )
}

function SecurityPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [needsMfa, setNeedsMfa] = useState(false)

  useEffect(() => {
    let active = true
    listSecurityEvents(100)
      .then((result) => {
        if (active) setEvents(result)
      })
      .catch((cause) => {
        if (!active) return
        setError(messageOf(cause))
        setNeedsMfa(cause instanceof ApiError && cause.status === 403)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div>
      <p className="text-body-md text-body">
        Authentication, MFA, and administrator actions, newest first.
      </p>
      {needsMfa && <MfaNotice />}
      {error && !needsMfa && (
        <p role="alert" className="mt-4 text-body-md text-error">
          {error}
        </p>
      )}
      <EventTable events={events} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export function Admin() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('users')

  if (!user) {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <Card className="flex flex-col items-start gap-3 p-10">
          <span className="text-body-sm text-mute">AUTH REQUIRED</span>
          <h1 className="text-heading-md text-ink">Sign in as an administrator.</h1>
          <Link to="/login" className="text-body-md text-link hover:underline">
            Go to sign in
          </Link>
        </Card>
      </section>
    )
  }

  if (user.role !== 'admin') {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <Card className="flex flex-col items-start gap-3 p-10">
          <span className="text-body-sm text-error">FORBIDDEN</span>
          <h1 className="text-heading-md text-ink">Administrator access required.</h1>
          <Link to="/auctions" className="text-body-md text-link hover:underline">
            Back to auctions
          </Link>
        </Card>
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <Eyebrow>Administration</Eyebrow>
      <h1 className="mt-3 text-heading-lg text-ink">Security console</h1>
      <p className="mt-2 max-w-2xl text-body-md text-body">
        User administration, the tamper-evident audit ledger, and security
        events. Administrators can cancel auctions but never bid, close, or
        award them.
      </p>

      <div className="mt-8 flex items-center gap-1 rounded-sm border border-hairline bg-elevated p-1">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-pressed={tab === item.id}
            className={cn(
              'h-8 rounded-sm px-3 text-btn-md transition-colors',
              tab === item.id
                ? 'bg-canvas text-ink shadow-whisper'
                : 'text-mute hover:text-body',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === 'users' && <UsersPanel />}
        {tab === 'audit' && <AuditPanel />}
        {tab === 'security' && <SecurityPanel />}
      </div>
    </section>
  )
}