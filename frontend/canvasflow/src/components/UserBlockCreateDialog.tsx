/**
 * Large editor dialog to create a custom block from the sidebar (+).
 */
import React, { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { starterForFilename } from '../userBlockTemplate';
import type { ThemeMode } from '../types';
import PythonScriptEditor from './PythonScriptEditor';

export default function UserBlockCreateDialog({
  open,
  onOpenChange,
  themeMode,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  themeMode: ThemeMode;
}) {
  const setSchemas = useFlowStore((s) => s.setSchemas);
  const [filename, setFilename] = useState('my_block.py');
  const [code, setCode] = useState(() => starterForFilename('my_block.py'));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!open) return;
    setFilename('my_block.py');
    setCode(starterForFilename('my_block.py'));
    setMsg('');
    setBusy(false);
  }, [open]);

  const applyFilenameToTemplate = (raw: string) => {
    let name = String(raw || '').trim();
    if (!name) return;
    if (!name.toLowerCase().endsWith('.py')) name = `${name}.py`;
    const prevName = filename;
    setFilename(name);
    // Only rewrite code if user hasn't customized beyond the previous starter
    setCode((prev) => {
      const prevStarter = starterForFilename(prevName);
      if (prev.trim() === prevStarter.trim()) return starterForFilename(name);
      return prev;
    });
  };

  const handleSave = async () => {
    let name = String(filename || '').trim();
    if (!name) {
      setMsg('请填写文件名');
      return;
    }
    if (!name.toLowerCase().endsWith('.py')) name = `${name}.py`;
    if (!/^[A-Za-z0-9_\-]+\.py$/.test(name) || name.startsWith('_')) {
      setMsg('文件名仅允许字母数字_-，且不能以下划线开头');
      return;
    }
    if (!code.trim()) {
      setMsg('代码不能为空');
      return;
    }
    setBusy(true);
    setMsg('');
    try {
      const res = await bridge.writeUserBlockFile(name, code);
      if (!res?.ok) {
        setMsg(res?.error || '保存失败');
        return;
      }
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) setSchemas(list);
      setMsg(`已保存 ${name}，侧栏「自定义」已更新`);
      onOpenChange(false);
    } catch (e: any) {
      setMsg(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(960px,94vw)] max-w-none gap-3 p-4 sm:max-w-none">
        <DialogHeader className="pr-8">
          <DialogTitle>新建自定义积木</DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1 min-w-[12rem] flex-1">
            <Label className="text-[11px] opacity-70">文件名</Label>
            <Input
              className="h-8 text-xs font-mono"
              value={filename}
              placeholder="my_block.py"
              onChange={(e) => setFilename(e.target.value)}
              onBlur={() => applyFilenameToTemplate(filename)}
            />
          </div>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => void handleSave()}
            className="h-8"
          >
            <Save className="w-3.5 h-3.5" />
            保存到积木库
          </Button>
        </div>
        <p className="text-[11px] opacity-55 leading-relaxed -mt-1">
          需导出 <code className="font-mono">SCHEMA</code> 与{' '}
          <code className="font-mono">handler</code>；保存后出现在侧栏「自定义」。可用下方示例与
          Ctrl+Space 补全。
        </p>
        <PythonScriptEditor
          value={code}
          onChange={setCode}
          themeMode={themeMode}
          mode="block"
          height="62vh"
          allowExpand={false}
        />
        {msg ? <p className="text-xs opacity-70">{msg}</p> : null}
      </DialogContent>
    </Dialog>
  );
}
