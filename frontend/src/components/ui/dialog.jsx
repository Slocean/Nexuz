import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

function Dialog({ ...props }) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger({ ...props }) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal({ ...props }) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose({ ...props }) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogOverlay({ className, ...props }) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        'fixed inset-0 z-[100] bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        className,
      )}
      {...props}
    />
  );
}

function DialogContent({ className, children, showClose = true, showOverlay = true, ...props }) {
  return (
    <DialogPortal>
      {showOverlay ? <DialogOverlay /> : null}
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          'fixed left-1/2 top-1/2 z-[101] grid w-[min(440px,92vw)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-2xl border border-[var(--border)] bg-[var(--popover)] p-5 text-[var(--popover-foreground)] shadow-2xl outline-none backdrop-blur-xl',
          'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
          className,
        )}
        {...props}
      >
        {children}
        {showClose ? (
          <DialogPrimitive.Close className="absolute right-3 top-3 rounded-lg p-1.5 text-[var(--popover-foreground)] opacity-60 hover:opacity-100 hover:bg-black/5 dark:hover:bg-white/10 transition-colors cursor-pointer">
            <X className="w-4 h-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }) {
  return <div className={cn('flex flex-col gap-1.5 pr-6', className)} {...props} />;
}

function DialogFooter({ className, ...props }) {
  return (
    <div className={cn('flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-1', className)} {...props} />
  );
}

function DialogTitle({ className, ...props }) {
  return (
    <DialogPrimitive.Title
      className={cn(
        'font-display text-base font-semibold leading-none text-[var(--popover-foreground)]',
        className,
      )}
      {...props}
    />
  );
}

function DialogDescription({ className, ...props }) {
  return (
    <DialogPrimitive.Description
      className={cn('text-xs text-[var(--muted-foreground)] leading-relaxed whitespace-pre-line', className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
};
