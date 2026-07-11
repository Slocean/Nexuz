import React, { useEffect, useMemo, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import {
  AlignLeft,
  CheckCircle2,
  AlertTriangle,
  Check,
  FileCode2,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { flowToJson, useFlowStore } from '@/store/flowModelStore';
import { bridge } from '@/bridge';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';

interface CodeEditorProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
}

export default function CodeEditor({ themeName, themeMode }: CodeEditorProps) {
  const flow = useFlowStore((s) => s.flow);
  const setFlow = useFlowStore((s) => s.setFlow);
  const filePath = useFlowStore((s) => s.filePath);
  const appendLog = useFlowStore((s) => s.appendLog);

  const colors = getThemeColors(themeName, themeMode);
  const canonical = useMemo(() => flowToJson(flow), [flow]);
  const lastAppliedRef = useRef(canonical);

  const [text, setText] = useState(canonical);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // Canvas → JSON when editor is clean (matches last applied)
  useEffect(() => {
    setText((prev) => {
      if (prev.trim() === lastAppliedRef.current.trim()) {
        lastAppliedRef.current = canonical;
        return canonical;
      }
      return prev;
    });
  }, [canonical]);

  const dirty = text.trim() !== canonical.trim();
  const autoApplyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [autoSync, setAutoSync] = useState(true);

  // Debounced JSON → canvas when valid
  useEffect(() => {
    if (!autoSync) return;
    if (text.trim() === canonical.trim()) return;
    if (autoApplyTimer.current) clearTimeout(autoApplyTimer.current);
    autoApplyTimer.current = setTimeout(async () => {
      try {
        const parsed = JSON.parse(text);
        const res = await bridge.validateFlow(parsed);
        if (res && res.ok === false) {
          setError(res.error || '校验失败');
          return;
        }
        const next = flowToJson(parsed);
        setFlow(parsed, filePath);
        setText(next);
        lastAppliedRef.current = next;
        setError(null);
        setOkMsg('已自动同步到画布');
        setTimeout(() => setOkMsg(null), 1200);
      } catch (e: any) {
        setError(`JSON 语法错误: ${e.message}`);
      }
    }, 800);
    return () => {
      if (autoApplyTimer.current) clearTimeout(autoApplyTimer.current);
    };
  }, [text, autoSync, canonical, filePath, setFlow]);

  const handleFormat = () => {
    try {
      const parsed = JSON.parse(text);
      const formatted = JSON.stringify(parsed, null, 2);
      setText(formatted);
      setError(null);
      setOkMsg('已格式化');
      setTimeout(() => setOkMsg(null), 1500);
    } catch (e: any) {
      setError(`JSON 语法错误: ${e.message}`);
    }
  };

  const handleValidate = async () => {
    try {
      const parsed = JSON.parse(text);
      const res = await bridge.validateFlow(parsed);
      if (!res || res.ok !== false) {
        setError(null);
        setOkMsg('校验通过');
        setTimeout(() => setOkMsg(null), 2000);
      } else {
        setError(res.error || '校验失败');
      }
    } catch (e: any) {
      setError(`JSON 语法错误: ${e.message}`);
    }
  };

  const handleApply = async () => {
    setApplying(true);
    setOkMsg(null);
    try {
      const parsed = JSON.parse(text);
      const res = await bridge.validateFlow(parsed);
      if (res && res.ok === false) {
        setError(res.error || '校验失败，未应用到画布');
        appendLog({ level: 'error', message: `JSON 校验失败: ${res.error}` });
        return;
      }
      const next = flowToJson(parsed);
      setFlow(parsed, filePath);
      setText(next);
      lastAppliedRef.current = next;
      setError(null);
      setOkMsg('已应用到画布');
      appendLog({ level: 'ok', message: 'JSON 已同步到画布' });
      setTimeout(() => setOkMsg(null), 2000);
    } catch (e: any) {
      setError(`无法应用: ${e.message}`);
    } finally {
      setApplying(false);
    }
  };

  const handleReset = () => {
    setText(canonical);
    lastAppliedRef.current = canonical;
    setError(null);
    setOkMsg('已重置为画布内容');
    setTimeout(() => setOkMsg(null), 1500);
  };

  return (
    <div
      style={{
        backgroundColor: themeMode === 'light' ? '#F8FAFC' : '#0A0D14',
        color: colors.text,
      }}
      className="flex-1 flex flex-col min-w-0 min-h-0"
    >
      <div
        style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        className="h-12 px-4 border-b flex items-center gap-2 shrink-0 backdrop-blur-xl"
      >
        <FileCode2 className="w-4 h-4 opacity-70" />
        <span className="font-display font-semibold text-sm">Flow JSON</span>
        {dirty && (
          <Badge variant="secondary" className="normal-case tracking-normal">
            未同步
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <label className="flex items-center gap-1.5 text-[10px] opacity-70 cursor-pointer mr-1">
            <input
              type="checkbox"
              checked={autoSync}
              onChange={(e) => setAutoSync(e.target.checked)}
              className="accent-blue-500"
            />
            自动同步
          </label>
          <Button variant="ghost" size="sm" onClick={handleReset} disabled={!dirty}>
            <RefreshCw className="w-3.5 h-3.5" />
            重置
          </Button>
          <Button variant="ghost" size="sm" onClick={handleFormat}>
            <AlignLeft className="w-3.5 h-3.5" />
            格式化
          </Button>
          <Button variant="outline" size="sm" onClick={handleValidate}>
            <CheckCircle2 className="w-3.5 h-3.5" />
            校验
          </Button>
          <Button
            size="sm"
            onClick={handleApply}
            disabled={applying}
            style={{ backgroundColor: colors.primary, color: '#fff' }}
          >
            <Check className="w-3.5 h-3.5" />
            应用到画布
          </Button>
        </div>
      </div>

      {(error || okMsg) && (
        <div
          className={`px-4 py-2 text-xs flex items-start gap-2 border-b ${
            error
              ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
              : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
          }`}
        >
          {error ? (
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          )}
          <span className="font-mono break-all">{error || okMsg}</span>
        </div>
      )}

      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          defaultLanguage="json"
          theme={themeMode === 'dark' ? 'vs-dark' : 'light'}
          value={text}
          onChange={(v) => setText(v ?? '')}
          options={{
            fontSize: 13,
            fontFamily: 'JetBrains Mono, ui-monospace, monospace',
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
            formatOnPaste: true,
          }}
        />
      </div>
    </div>
  );
}
