/*
 * Display helpers for money, dates, and countdowns.
 *
 * Money is stored everywhere as integer minor units (paise). Formatting is the
 * only place that divides by 100, so no arithmetic ever touches a float.
 */

const LOCALE_BY_CURRENCY: Record<string, string> = {
  INR: 'en-IN',
}

export function formatMoney(minorUnits: number, currency = 'INR'): string {
  const locale = LOCALE_BY_CURRENCY[currency] ?? 'en-US'
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(minorUnits / 100)
}

const dateTimeFormatter = new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function formatDateTime(iso: string): string {
  return dateTimeFormatter.format(new Date(iso))
}

export function isEnded(endsAt: string, now: number = Date.now()): boolean {
  return new Date(endsAt).getTime() <= now
}

export function formatRemaining(endsAt: string, now: number = Date.now()): string {
  const remaining = new Date(endsAt).getTime() - now
  if (remaining <= 0) return 'Ended'

  const totalSeconds = Math.floor(remaining / 1000)
  const days = Math.floor(totalSeconds / 86_400)
  const hours = Math.floor((totalSeconds % 86_400) / 3_600)
  const minutes = Math.floor((totalSeconds % 3_600) / 60)
  const seconds = totalSeconds % 60

  if (days > 0) return `${days}d ${hours}h left`
  if (hours > 0) return `${hours}h ${minutes}m left`
  if (minutes > 0) return `${minutes}m ${seconds}s left`
  return `${seconds}s left`
}

/** Convert a user-entered rupee string to integer paise. */
export function rupeesToMinor(value: string): number {
  return Math.round(Number(value) * 100)
}

/** Render integer paise as a plain rupee amount for form inputs. */
export function minorToRupees(minorUnits: number): string {
  return (minorUnits / 100).toFixed(2).replace(/\.00$/, '')
}