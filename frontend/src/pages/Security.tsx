import { Card } from '../components/ui/Card'
import { Eyebrow } from '../components/ui/Eyebrow'

const CONTROLS = [
  {
    area: 'Authentication',
    detail:
      'Argon2id password hashing, opaque server-side sessions, CSRF tokens, and TOTP MFA for admins.',
  },
  {
    area: 'Authorization',
    detail:
      'Deny-by-default routing, role checks on every route, and resource ownership checks to block IDOR.',
  },
  {
    area: 'Input & OWASP',
    detail:
      'Strict schema validation, parameterized queries, output escaping, CSP, HSTS, and rate limiting.',
  },
  {
    area: 'Audit integrity',
    detail:
      'Append-only events sealed with an HMAC-SHA256 hash chain and verified from the admin dashboard.',
  },
  {
    area: 'Bid integrity',
    detail:
      'Every bid is HMAC-signed and linked to the previous bid, making the ledger tamper-evident.',
  },
  {
    area: 'Secrets & transport',
    detail:
      'Secrets from the environment, encrypted TOTP seeds at rest, TLS, and secure cookie flags.',
  },
]

export function Security() {
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-16">
      <Eyebrow>Security model</Eyebrow>
      <h1 className="mt-3 max-w-2xl text-heading-lg text-ink">
        Six control areas, one audit trail.
      </h1>
      <p className="mt-3 max-w-2xl text-body-lg text-body">
        This scaffold will grow into a system where every privileged action is
        checked, logged, and verifiable. Controls are wired in per milestone and
        proven by the attack test suite.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {CONTROLS.map((control, index) => (
          <Card key={control.area} className="flex gap-4">
            <span className="text-body-sm text-mute">
              {String(index + 1).padStart(2, '0')}
            </span>
            <div>
              <h2 className="text-heading-md text-ink">{control.area}</h2>
              <p className="mt-2 text-body-md text-body">{control.detail}</p>
            </div>
          </Card>
        ))}
      </div>
    </section>
  )
}