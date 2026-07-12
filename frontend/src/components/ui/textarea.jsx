import * as React from 'react';
import { cn } from '@/lib/utils';

function Textarea({ className, ...props }) {
  return (
    <textarea
      className={cn(
        'flex min-h-[72px] w-full rounded-xl border border-[var(--border)] bg-black/[0.03] dark:bg-white/[0.03] px-3 py-2 text-sm text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-50 resize-none',
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
