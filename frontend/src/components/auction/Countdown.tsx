import { useEffect, useState } from 'react'
import { cn } from '../../lib/cn'
import { formatRemaining, isEnded } from '../../lib/format'

/*
 * One ticking clock per countdown is fine at this scale. If the list grows,
 * lift the interval into a single context so every card shares one timer.
 */
export function Countdown({
  endsAt,
  className,
}: {
  endsAt: string
  className?: string
}) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [])

  const ended = isEnded(endsAt, now)

  return (
    <span
      className={cn(
        'font-mono text-body-sm',
        ended ? 'text-mute' : 'text-ink',
        className,
      )}
    >
      {formatRemaining(endsAt, now)}
    </span>
  )
}