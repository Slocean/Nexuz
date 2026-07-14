import * as React from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { Check, ChevronDown, ChevronUp, Search } from 'lucide-react';
import { cn } from '@/lib/utils';

function Select(props) {
  return <SelectPrimitive.Root {...props} />;
}

function SelectGroup(props) {
  return <SelectPrimitive.Group {...props} />;
}
SelectGroup.displayName = 'SelectGroup';

function SelectValue(props) {
  return <SelectPrimitive.Value {...props} />;
}

function SelectTrigger({ className, children, ...props }) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        'flex h-9 w-full items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-black/[0.03] dark:bg-white/[0.03] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1 cursor-pointer',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="size-4 opacity-50 shrink-0" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

function collectText(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(collectText).join(' ');
  if (React.isValidElement(node)) return collectText(node.props?.children);
  return '';
}

function elementName(el) {
  if (!React.isValidElement(el)) return '';
  return el.type?.displayName || el.type?.name || '';
}

function filterSelectChildren(children, query) {
  const q = String(query || '')
    .trim()
    .toLowerCase();
  if (!q) return children;

  return React.Children.map(children, (child) => {
    if (!React.isValidElement(child)) return child;
    const name = elementName(child);

    if (child.type === SelectItem || name === 'SelectItem') {
      const hay = `${collectText(child.props.children)} ${child.props.value ?? ''}`.toLowerCase();
      return hay.includes(q) ? child : null;
    }

    if (child.type === SelectGroup || name === 'SelectGroup') {
      const filtered = filterSelectChildren(child.props.children, query);
      const kept = React.Children.toArray(filtered).filter(Boolean);
      if (!kept.length) return null;
      return React.cloneElement(child, child.props, filtered);
    }

    // Keep labels/separators; they may look odd if all items filtered — groups handle that.
    if (child.type === SelectLabel || name === 'SelectLabel') return child;
    if (child.type === SelectSeparator || name === 'SelectSeparator') return child;
    return child;
  });
}

function SelectContent({
  className,
  children,
  position = 'popper',
  searchable = true,
  searchPlaceholder = '输入搜索…',
  ...props
}) {
  const [query, setQuery] = React.useState('');
  const inputRef = React.useRef(null);

  const filtered = React.useMemo(
    () => (searchable ? filterSelectChildren(children, query) : children),
    [children, query, searchable],
  );
  const visibleCount = React.Children.toArray(filtered).filter(Boolean).length;

  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        className={cn(
          'relative z-50 max-h-72 min-w-[8rem] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] shadow-xl backdrop-blur-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
          position === 'popper' &&
            'data-[side=bottom]:translate-y-1 data-[side=top]:-translate-y-1',
          className,
        )}
        position={position}
        {...props}
      >
        {searchable ? (
          <div
            className="sticky top-0 z-10 flex items-center gap-1.5 border-b border-[var(--border)] bg-[var(--card)] px-2 py-1.5"
            // Keep focus / keys inside the search field
            onKeyDown={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <Search className="size-3.5 shrink-0 opacity-50" />
            <input
              ref={inputRef}
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              className="h-7 w-full bg-transparent text-sm outline-none placeholder:opacity-40"
              onKeyDown={(e) => {
                // Prevent Radix typeahead from stealing keystrokes
                e.stopPropagation();
                if (e.key === 'Escape') {
                  if (query) {
                    e.preventDefault();
                    setQuery('');
                  }
                }
              }}
            />
          </div>
        ) : null}

        <SelectPrimitive.ScrollUpButton className="flex cursor-default items-center justify-center py-1">
          <ChevronUp className="size-4" />
        </SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport
          className={cn(
            'p-1',
            position === 'popper' &&
              'w-full min-w-[var(--radix-select-trigger-width)]',
          )}
        >
          {searchable && visibleCount === 0 ? (
            <div className="px-2 py-3 text-center text-xs opacity-50">无匹配项</div>
          ) : (
            filtered
          )}
        </SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="flex cursor-default items-center justify-center py-1">
          <ChevronDown className="size-4" />
        </SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}
SelectContent.displayName = 'SelectContent';

function SelectLabel({ className, ...props }) {
  return (
    <SelectPrimitive.Label
      className={cn('px-2 py-1.5 text-xs font-semibold text-[var(--muted-foreground)]', className)}
      {...props}
    />
  );
}
SelectLabel.displayName = 'SelectLabel';

function SelectItem({ className, children, ...props }) {
  return (
    <SelectPrimitive.Item
      className={cn(
        'relative flex w-full cursor-pointer select-none items-center rounded-lg py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-black/5 dark:focus:bg-white/5 data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        className,
      )}
      {...props}
    >
      <span className="absolute right-2 flex size-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="size-3.5 text-emerald-500" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}
SelectItem.displayName = 'SelectItem';

function SelectSeparator({ className, ...props }) {
  return (
    <SelectPrimitive.Separator
      className={cn('-mx-1 my-1 h-px bg-[var(--border)]', className)}
      {...props}
    />
  );
}
SelectSeparator.displayName = 'SelectSeparator';

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
};
