import * as React from 'react';
import * as ScrollAreaPrimitive from '@radix-ui/react-scroll-area';
import { cn } from '@/lib/utils';

function ScrollArea({ className, children, ...props }) {
  return (
    <ScrollAreaPrimitive.Root className={cn('relative overflow-hidden min-w-0', className)} {...props}>
      <ScrollAreaPrimitive.Viewport className="h-full w-full max-w-full rounded-[inherit] [&>div]:!block [&>div]:!min-w-0 [&>div]:!w-full [&>div]:!max-w-full">
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollAreaPrimitive.Scrollbar
        orientation="vertical"
        className="flex touch-none select-none p-0.5 transition-colors"
      >
        <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-slate-400/30" />
      </ScrollAreaPrimitive.Scrollbar>
    </ScrollAreaPrimitive.Root>
  );
}

export { ScrollArea };
