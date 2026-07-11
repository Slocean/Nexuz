import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '@/lib/utils';

function Tabs({ className, ...props }) {
  return <TabsPrimitive.Root className={cn('flex flex-col', className)} {...props} />;
}

function TabsList({ className, ...props }) {
  return (
    <TabsPrimitive.List
      className={cn('flex gap-1 border-b border-black/5 dark:border-white/5 p-2', className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'flex-1 py-2 rounded-xl text-xs font-semibold uppercase tracking-wider transition-all duration-200 hover:bg-black/5 dark:hover:bg-white/5 data-[state=active]:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] data-[state=active]:text-[var(--primary)] text-[var(--muted-foreground)] cursor-pointer',
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }) {
  return <TabsPrimitive.Content className={cn('flex-1 outline-none', className)} {...props} />;
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
