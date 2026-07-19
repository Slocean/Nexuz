import type { ComponentType } from 'react';

type UiComponent = ComponentType<any>;

declare module '@/components/ui/button' {
  export const Button: UiComponent;
  export const buttonVariants: (...args: any[]) => string;
}

declare module '@/components/ui/input' {
  export const Input: UiComponent;
}

declare module '@/components/ui/textarea' {
  export const Textarea: UiComponent;
}

declare module '@/components/ui/label' {
  export const Label: UiComponent;
}

declare module '@/components/ui/scroll-area' {
  export const ScrollArea: UiComponent;
  export const ScrollBar: UiComponent;
}

declare module '@/components/ui/separator' {
  export const Separator: UiComponent;
}

declare module '@/components/ui/checkbox' {
  export const Checkbox: UiComponent;
}

declare module '@/components/ui/badge' {
  export const Badge: UiComponent;
  export const badgeVariants: (...args: any[]) => string;
}

declare module '@/components/ui/select' {
  export const Select: UiComponent;
  export const SelectGroup: UiComponent;
  export const SelectValue: UiComponent;
  export const SelectTrigger: UiComponent;
  export const SelectContent: UiComponent;
  export const SelectLabel: UiComponent;
  export const SelectItem: UiComponent;
  export const SelectSeparator: UiComponent;
}

declare module '@/components/ui/tabs' {
  export const Tabs: UiComponent;
  export const TabsList: UiComponent;
  export const TabsTrigger: UiComponent;
  export const TabsContent: UiComponent;
}

declare module '@/components/ui/dialog' {
  export const Dialog: UiComponent;
  export const DialogTrigger: UiComponent;
  export const DialogPortal: UiComponent;
  export const DialogClose: UiComponent;
  export const DialogOverlay: UiComponent;
  export const DialogContent: UiComponent;
  export const DialogHeader: UiComponent;
  export const DialogFooter: UiComponent;
  export const DialogTitle: UiComponent;
  export const DialogDescription: UiComponent;
}

declare module '@/components/ui/alert-dialog' {
  export const AlertDialog: UiComponent;
  export const AlertDialogPortal: UiComponent;
  export const AlertDialogOverlay: UiComponent;
  export const AlertDialogTrigger: UiComponent;
  export const AlertDialogContent: UiComponent;
  export const AlertDialogHeader: UiComponent;
  export const AlertDialogFooter: UiComponent;
  export const AlertDialogTitle: UiComponent;
  export const AlertDialogDescription: UiComponent;
  export const AlertDialogAction: UiComponent;
  export const AlertDialogCancel: UiComponent;
}

declare module '@/components/ui/dropdown-menu' {
  export const DropdownMenu: UiComponent;
  export const DropdownMenuTrigger: UiComponent;
  export const DropdownMenuContent: UiComponent;
  export const DropdownMenuItem: UiComponent;
  export const DropdownMenuCheckboxItem: UiComponent;
  export const DropdownMenuRadioItem: UiComponent;
  export const DropdownMenuLabel: UiComponent;
  export const DropdownMenuSeparator: UiComponent;
  export const DropdownMenuShortcut: UiComponent;
  export const DropdownMenuGroup: UiComponent;
  export const DropdownMenuPortal: UiComponent;
  export const DropdownMenuSub: UiComponent;
  export const DropdownMenuSubContent: UiComponent;
  export const DropdownMenuSubTrigger: UiComponent;
  export const DropdownMenuRadioGroup: UiComponent;
}
