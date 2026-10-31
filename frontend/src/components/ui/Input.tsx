import { forwardRef } from 'react'
import type { InputHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        'h-9 w-full rounded-sm border border-hairline bg-elevated px-3 text-body-md text-ink transition-colors',
        'placeholder:text-faint',
        'focus:border-link focus:outline-none focus:ring-2 focus:ring-link/20',
        'disabled:bg-hairline-soft disabled:text-faint',
        className,
      )}
      {...props}
    />
  )
})