import * as React from 'react';
import * as LabelPrimitive from '@radix-ui/react-label';
import { cn } from '@/lib/utils';

function Label({ className, ...props }) {
  return (
    <LabelPrimitive.Root
      className={cn('text-xs font-medium tracking-wide opacity-75', className)}
      {...props}
    />
  );
}

export { Label };
