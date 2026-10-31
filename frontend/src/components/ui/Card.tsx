import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  elevated?: boolean
}

export function Card({ elevated = false, className, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-md border border-hairline bg-elevated p-6',
        elevated && 'shadow-float',
        className,
      )}
      {...props}
    />
  )
}