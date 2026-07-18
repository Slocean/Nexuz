/**
 * Monaco-based Python editor for python_script nodes and user_blocks files.
 * Provides snippet examples + keyword / API completions.
 */
import React, { useEffect, useRef, useState } from 'react';
import Editor, { OnMount } from '@monaco-editor/react';
import { Maximize2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ThemeMode } from '../types';

export type PythonEditorMode = 'script' | 'block';

const SCRIPT_EXAMPLES: { id: string; label: string; code: string }[] = [
  {
    id: 'basic',
    label: '基础：计算结果',
    code: `out["result"] = 1 + 1
print("sum =", out["result"])
`,
  },
  {
    id: 'inputs',
    label: '读取注入变量',
    code: `# Inspector「注入变量」里的键会出现在 inputs 中
x = inputs.get("x", 0)
out["result"] = x * 2
print("x=", x, "result=", out["result"])
`,
  },
  {
    id: 'context',
    label: '读取流程变量 / 上游输出',
    code: `# $变量 或 上游节点输出，例如 context.get("node1.text")
name = context.get("$name") or context.get("name") or ""
out["result"] = f"hello, {name}"
`,
  },
  {
    id: 'json',
    label: 'JSON 解析（白名单 import）',
    code: `import json

raw = inputs.get("body") or "{}"
data = json.loads(raw) if isinstance(raw, str) else raw
out["result"] = data
print(type(data).__name__)
`,
  },
  {
    id: 'fail',
    label: '标记失败（不中断流程）',
    code: `val = inputs.get("value")
if not val:
    out["ok"] = False
    out["error"] = "value 为空"
else:
    out["result"] = val
`,
  },
];

const BLOCK_EXAMPLES: { id: string; label: string; code: string }[] = [
  {
    id: 'echo',
    label: '最小积木：回显',
    code: `SCHEMA = {
    "type": "my_echo",
    "label": "我的回显",
    "category": "自定义",
    "inputs": [
        {
            "name": "text",
            "type": "string",
            "label": "文本",
            "default": "",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "text", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    text = "" if params.get("text") is None else str(params.get("text"))
    return {"ok": True, "text": text}
`,
  },
  {
    id: 'select',
    label: '带下拉参数',
    code: `SCHEMA = {
    "type": "my_format",
    "label": "格式化文本",
    "category": "自定义",
    "inputs": [
        {
            "name": "mode",
            "type": "select",
            "label": "模式",
            "options": ["upper", "lower"],
            "default": "upper",
            "option_labels": {"upper": "大写", "lower": "小写"},
        },
        {
            "name": "text",
            "type": "string",
            "label": "文本",
            "default": "",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "text", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    text = str(params.get("text") or "")
    mode = str(params.get("mode") or "upper")
    if mode == "lower":
        return {"ok": True, "text": text.lower(), "error": ""}
    return {"ok": True, "text": text.upper(), "error": ""}
`,
  },
  {
    id: 'error',
    label: '失败返回 ok/error',
    code: `SCHEMA = {
    "type": "my_require",
    "label": "非空校验",
    "category": "自定义",
    "inputs": [
        {"name": "text", "type": "string", "label": "文本", "default": "", "bindable": True},
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "text", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    text = str(params.get("text") or "").strip()
    if not text:
        return {"ok": False, "text": "", "error": "文本不能为空"}
    return {"ok": True, "text": text, "error": ""}
`,
  },
];

const SCRIPT_KEYWORDS: { label: string; detail: string; insert: string }[] = [
  { label: 'out', detail: '写入输出字典', insert: 'out' },
  { label: 'out["result"]', detail: '主结果（下游可绑定）', insert: 'out["result"]' },
  { label: 'out["ok"]', detail: '是否成功', insert: 'out["ok"]' },
  { label: 'out["error"]', detail: '错误信息', insert: 'out["error"]' },
  { label: 'inputs', detail: '注入变量字典', insert: 'inputs' },
  { label: 'inputs.get', detail: '安全读取注入', insert: 'inputs.get("$1", $2)' },
  { label: 'context', detail: '流程上下文（只读）', insert: 'context' },
  { label: 'context.get', detail: '读 $变量 / node.field', insert: 'context.get("$1")' },
  { label: 'import json', detail: '白名单模块', insert: 'import json\n' },
  { label: 'import math', detail: '白名单模块', insert: 'import math\n' },
  { label: 'import re', detail: '白名单模块', insert: 'import re\n' },
  { label: 'import datetime', detail: '白名单模块', insert: 'import datetime\n' },
  { label: 'print', detail: '输出到 printed', insert: 'print($1)' },
];

const BLOCK_KEYWORDS: { label: string; detail: string; insert: string }[] = [
  { label: 'SCHEMA', detail: '积木描述（必填）', insert: 'SCHEMA' },
  { label: 'handler', detail: '执行函数（必填）', insert: 'def handler(params, context, **kwargs):\n    $0' },
  { label: 'params', detail: '节点参数', insert: 'params' },
  { label: 'context', detail: '流程上下文', insert: 'context' },
  { label: 'bindable', detail: '允许变量绑定', insert: '"bindable": True' },
  { label: 'category', detail: '侧栏分类', insert: '"category": "自定义"' },
  { label: 'return ok', detail: '成功返回', insert: 'return {"ok": True}' },
  { label: 'return error', detail: '失败返回', insert: 'return {"ok": False, "error": "$1"}' },
];

let completionDisposable: { dispose: () => void } | null = null;
let completionRefCount = 0;
let completionMode: PythonEditorMode = 'script';

function ensureCompletionProvider(monaco: any, mode: PythonEditorMode) {
  completionMode = mode;
  if (completionDisposable) return;
  completionDisposable = monaco.languages.registerCompletionItemProvider('python', {
    triggerCharacters: ['.', '"', "'", '['],
    provideCompletionItems(_model: any, position: any) {
      const model = _model;
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };
      const Kind = monaco.languages.CompletionItemKind;
      const list = completionMode === 'block' ? BLOCK_KEYWORDS : SCRIPT_KEYWORDS;
      const suggestions = list.map((item) => ({
        label: item.label,
        kind: Kind.Keyword,
        detail: item.detail,
        insertText: item.insert,
        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
        range,
      }));
      for (const name of ['True', 'False', 'None', 'len', 'str', 'int', 'float', 'list', 'dict', 'range']) {
        suggestions.push({
          label: name,
          kind: Kind.Keyword,
          insertText: name,
          range,
        });
      }
      return { suggestions };
    },
  });
}

function retainCompletion(monaco: any, mode: PythonEditorMode) {
  ensureCompletionProvider(monaco, mode);
  completionRefCount += 1;
  completionMode = mode;
}

function releaseCompletion() {
  completionRefCount = Math.max(0, completionRefCount - 1);
  if (completionRefCount === 0 && completionDisposable) {
    completionDisposable.dispose();
    completionDisposable = null;
  }
}

function PythonEditorChrome({
  value,
  onChange,
  themeMode,
  mode = 'script',
  height = 220,
  className = '',
  allowExpand = true,
  onExpand,
}: {
  value: string;
  onChange: (next: string) => void;
  themeMode: ThemeMode;
  mode?: PythonEditorMode;
  height?: number | string;
  className?: string;
  allowExpand?: boolean;
  onExpand?: () => void;
}) {
  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const examples = mode === 'block' ? BLOCK_EXAMPLES : SCRIPT_EXAMPLES;

  useEffect(() => {
    return () => {
      releaseCompletion();
      editorRef.current = null;
      monacoRef.current = null;
    };
  }, []);

  useEffect(() => {
    completionMode = mode;
  }, [mode]);

  const onMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    retainCompletion(monaco, mode);
    editor.updateOptions({
      fontSize: 12,
      fontFamily: 'JetBrains Mono, ui-monospace, monospace',
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      automaticLayout: true,
      tabSize: 4,
      wordWrap: 'on',
      lineNumbers: 'on',
      suggestOnTriggerCharacters: true,
      quickSuggestions: true,
      snippetSuggestions: 'inline',
    });
  };

  const applyExample = (id: string) => {
    const ex = examples.find((e) => e.id === id);
    if (!ex) return;
    onChange(ex.code);
    requestAnimationFrame(() => editorRef.current?.focus());
  };

  return (
    <div
      className={`rounded-md border overflow-hidden ${className}`}
      style={{ borderColor: 'var(--border, rgba(128,128,128,0.35))' }}
    >
      <div
        className="flex flex-wrap items-center gap-2 px-2 py-1.5 border-b bg-black/[0.03] dark:bg-white/[0.04]"
        style={{ borderColor: 'inherit' }}
      >
        <span className="text-[10px] opacity-60 shrink-0">示例</span>
        <Select onValueChange={applyExample}>
          <SelectTrigger className="h-7 text-[11px] w-[11rem]">
            <SelectValue placeholder="插入代码示例…" />
          </SelectTrigger>
          {/* Above Dialog (z-101); default Select is z-50 and gets trapped underneath */}
          <SelectContent className="z-[200]" searchable={false}>
            {examples.map((ex) => (
              <SelectItem key={ex.id} value={ex.id} className="text-xs">
                {ex.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex flex-wrap gap-1">
          {examples.slice(0, 2).map((ex) => (
            <Button
              key={ex.id}
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-[10px] opacity-80"
              onClick={() => applyExample(ex.id)}
            >
              {ex.label.split('：')[0] || ex.label}
            </Button>
          ))}
        </div>
        <span className="text-[10px] opacity-45 ml-auto hidden sm:inline">
          {mode === 'script'
            ? '提示：out / inputs / context · Ctrl+Space'
            : '提示：SCHEMA / handler · Ctrl+Space'}
        </span>
        {allowExpand && onExpand ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 shrink-0"
            title="放大编辑"
            onClick={onExpand}
          >
            <Maximize2 className="w-3.5 h-3.5 opacity-80" />
          </Button>
        ) : null}
      </div>
      <Editor
        height={height}
        defaultLanguage="python"
        language="python"
        theme={themeMode === 'dark' ? 'vs-dark' : 'light'}
        value={value ?? ''}
        onChange={(v) => onChange(v ?? '')}
        onMount={onMount}
        options={{
          fontSize: 12,
          fontFamily: 'JetBrains Mono, ui-monospace, monospace',
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 4,
          wordWrap: 'on',
        }}
      />
    </div>
  );
}

export default function PythonScriptEditor({
  value,
  onChange,
  themeMode,
  mode = 'script',
  height = 220,
  className = '',
  allowExpand = true,
}: {
  value: string;
  onChange: (next: string) => void;
  themeMode: ThemeMode;
  mode?: PythonEditorMode;
  height?: number | string;
  className?: string;
  /** Show maximize button (default true). Nested expanded editor sets false. */
  allowExpand?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      {expanded && allowExpand ? (
        <div
          className={`rounded-md border flex items-center justify-center text-[11px] opacity-55 ${className}`}
          style={{
            borderColor: 'var(--border, rgba(128,128,128,0.35))',
            height: typeof height === 'number' ? height : 220,
          }}
        >
          已在放大窗口中编辑…
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 ml-2 text-[11px]"
            onClick={() => setExpanded(true)}
          >
            重新打开
          </Button>
        </div>
      ) : (
        <PythonEditorChrome
          value={value}
          onChange={onChange}
          themeMode={themeMode}
          mode={mode}
          height={height}
          className={className}
          allowExpand={allowExpand}
          onExpand={() => setExpanded(true)}
        />
      )}

      {allowExpand ? (
        <Dialog open={expanded} onOpenChange={setExpanded}>
          <DialogContent className="w-[min(960px,94vw)] max-w-none gap-3 p-4 sm:max-w-none">
            <DialogHeader className="pr-8">
              <DialogTitle>
                {mode === 'script' ? '编辑 Python 脚本' : '编辑自定义积木'}
              </DialogTitle>
            </DialogHeader>
            <PythonEditorChrome
              value={value}
              onChange={onChange}
              themeMode={themeMode}
              mode={mode}
              height="70vh"
              allowExpand={false}
            />
            <div className="flex justify-end">
              <Button type="button" size="sm" onClick={() => setExpanded(false)}>
                完成
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
