import * as React from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { Check, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';

function Checkbox({ className, checked, ...props }) {
  return (
    <CheckboxPrimitive.Root
      checked={checked}
      className={cn(
        'peer size-4 shrink-0 rounded-md border-2 border-[color-mix(in_srgb,var(--foreground)_35%,transparent)] bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] shadow-sm outline-none transition-colors',
        'hover:border-[color-mix(in_srgb,var(--foreground)_55%,transparent)]',
        'focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-1',
        'data-[state=checked]:bg-[var(--primary)] data-[state=checked]:border-[var(--primary)] data-[state=checked]:text-white data-[state=checked]:hover:border-[var(--primary)]',
        'data-[state=indeterminate]:bg-[var(--primary)] data-[state=indeterminate]:border-[var(--primary)] data-[state=indeterminate]:text-white',
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
        {checked === 'indeterminate' ? (
          <Minus className="size-3 stroke-[3]" />
        ) : (
          <Check className="size-3 stroke-[3]" />
        )}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
