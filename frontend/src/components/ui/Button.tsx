import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'primary-sm' | 'ghost-sm'

/*
 * Shape carries meaning in the Geist system: full pills are for marketing
 * surfaces, tight 6px squares are for in-app chrome.
 */
const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    'h-11 rounded-pill bg-primary px-3.5 text-btn-lg text-on-primary hover:bg-ink/90',
  secondary:
    'h-11 rounded-pill border border-hairline bg-elevated px-3.5 text-btn-lg text-ink hover:bg-hairline-soft',
  'primary-sm':
    'h-8 rounded-sm bg-primary px-1.5 text-btn-md text-on-primary hover:bg-ink/90',
  'ghost-sm':
    'h-8 rounded-sm border border-hairline bg-elevated px-1.5 text-btn-md text-ink hover:bg-hairline-soft',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

export function Button({
  variant = 'primary',
  className,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        VARIANT_CLASSES[variant],
        className,
      )}
      {...props}
    />
  )
}