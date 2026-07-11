import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] cursor-pointer active:scale-[0.98]',
  {
    variants: {
      variant: {
        default: 'bg-[var(--primary)] text-white shadow-sm hover:opacity-90',
        secondary: 'bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10',
        ghost: 'hover:bg-black/5 dark:hover:bg-white/5',
        outline: 'border border-[var(--border)] bg-transparent hover:bg-black/5 dark:hover:bg-white/5',
        destructive: 'bg-[var(--destructive)] text-white hover:opacity-90',
        soft: 'border border-transparent hover:border-white/10',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-xl px-3 text-xs',
        lg: 'h-10 rounded-2xl px-5',
        icon: 'h-10 w-10 rounded-2xl',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

function Button({ className, variant, size, asChild = false, ...props }) {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
