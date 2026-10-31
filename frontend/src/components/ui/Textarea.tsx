import { forwardRef } from 'react'
import type { TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(
        'w-full rounded-sm border border-hairline bg-elevated px-3 py-2 text-body-md text-ink transition-colors',
        'placeholder:text-faint',
        'focus:border-link focus:outline-none focus:ring-2 focus:ring-link/20',
        'disabled:bg-hairline-soft disabled:text-faint',
        className,
      )}
      {...props}
    />
  )
})