import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function Eyebrow({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <p className={cn('font-mono text-eyebrow uppercase text-mute', className)}>
      {children}
    </p>
  )
}