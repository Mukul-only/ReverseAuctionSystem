import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export type BadgeTone = 'neutral' | 'active' | 'warning' | 'danger'

const DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-mute',
  active: 'bg-link',
  warning: 'bg-warning',
  danger: 'bg-error',
}

export interface BadgeProps {
  tone?: BadgeTone
  className?: string
  children: ReactNode
}

/*
 * Status is carried by a label plus a small dot — never colour alone.
 */
export function Badge({ tone = 'neutral', className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-hairline bg-elevated px-2 py-0.5 text-body-sm text-body',
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full', DOT_CLASSES[tone])} />
      {children}
    </span>
  )
}