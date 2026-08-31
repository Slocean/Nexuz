/**
 * file_or_dir 路径输入框（素材缩放 / 透明图切割 / 精灵图切图等节点使用）：
 * - 手动填写 / 上游绑定
 * - 「文件」「文件夹」系统对话框
 * - OS 拖入文件夹或图片（真实路径由 pywebview 原生侧补全，见 backend/main.py）
 */
import React, { useCallback, useRef, useState } from 'react';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import BindableInput from './BindableInput';
import { useAppDialog } from './AppDialogs';
import { armNativeDropTarget, disarmNativeDropTarget, pickDropValue } from '../hooks/useNativeFileDrop';

const KNOWN_FILE_EXT = /\.[A-Za-z0-9]{1,6}$/;

function acceptExts(accept?: string | null): Set<string> | null {
  const exts = String(accept || '')
    .split(';')
    .map(s => s.trim().toLowerCase())
    .map(s => (s.startsWith('*.') ? s.slice(1) : s))
    .filter(s => s.startsWith('.'));
  return exts.length ? new Set(exts) : null;
}

export default function FileOrDirField({
  value,
  onChange,
  currentNodeId,
  schemaMap,
  placeholder,
  accept,
  scope,
}: {
  value: any;
  onChange: (next: any) => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
  placeholder?: string;
  accept?: string | null;
  scope?: string;
}) {
  const { alert } = useAppDialog();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const applyPath = useCallback(
    (path: string) => {
      const p = String(path || '').trim();
      if (p) onChange(p);
    },
    [onChange],
  );

  const armDropTarget = useCallback(() => {
    armNativeDropTarget(paths => {
      const path = pickDropValue(paths);
      if (!path) return;
      // 有扩展名的按 accept 白名单校验；无扩展名视为文件夹直接接受
      const exts = acceptExts(accept);
      const m = path.match(KNOWN_FILE_EXT);
      if (exts && m && !exts.has(m[0].toLowerCase())) {
        void alert({
          title: '不支持的文件类型',
          description: `${path}\n请拖入图片文件或文件夹（支持 ${accept}）`,
        });
        return;
      }
      applyPath(path);
    });
  }, [accept, applyPath]);

  const pickFile = async () => {
    const picked = await bridge.pickLocalPath?.('open', null, accept, scope);
    if (picked?.ok && picked.path) {
      applyPath(String(picked.path));
      return;
    }
    if (picked?.cancelled) return;
    await alert({
      title: '选择失败',
      description: picked?.error || '无法打开文件对话框，请手动填写路径',
    });
  };

  const pickFolder = async () => {
    const picked = await bridge.pickLocalPath?.('folder', null, null, scope);
    if (picked?.ok && picked.path) {
      applyPath(String(picked.path));
      return;
    }
    if (picked?.cancelled) return;
    await alert({
      title: '选择失败',
      description: picked?.error || '无法打开文件夹对话框，请手动填写路径',
    });
  };

  return (
    <div className="flex-1 min-w-0">
      <div
        ref={wrapRef}
        className="relative"
        onDragEnter={e => {
          e.preventDefault();
          setDragOver(true);
          armDropTarget();
        }}
        onDragOver={e => {
          e.preventDefault();
          setDragOver(true);
          armDropTarget();
        }}
        onDragLeave={e => {
          e.preventDefault();
          if (!wrapRef.current?.contains(e.relatedTarget as Node)) {
            setDragOver(false);
            disarmNativeDropTarget();
          }
        }}
        onDrop={e => {
          // 只 preventDefault，不 stopPropagation：
          // pywebview 的 document 级 drop 监听依赖原生事件冒泡到 document
          // 才能把真实文件路径补全回来，拦掉冒泡就永远收不到路径。
          e.preventDefault();
          // 真实路径在原生侧、drop 之后异步到达：保持挂载，靠 TTL 兜底
          setDragOver(false);
        }}
      >
        <BindableInput
          value={value ?? ''}
          inputType="string"
          currentNodeId={currentNodeId}
          schemaMap={schemaMap}
          onChange={onChange}
          placeholder={placeholder || '文件路径或文件夹路径'}
          multiline
          valueLabel="路径"
          trailing={
            <>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0 px-2"
                title="选择文件"
                onClick={() => void pickFile()}
              >
                文件
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0 px-2"
                title="选择文件夹（批量处理其中所有图片）"
                onClick={() => void pickFolder()}
              >
                文件夹
              </Button>
            </>
          }
        />
        {dragOver ? (
          <div
            className="absolute inset-0 z-10 flex items-center justify-center rounded-md border border-dashed border-[var(--primary)] bg-[var(--primary)]/10 pointer-events-none"
            title="拖入文件夹或图片"
          >
            <span className="text-xs font-medium text-[var(--primary)]">松开以填入路径</span>
          </div>
        ) : null}
      </div>
      <p className="mt-0.5 text-[10px] opacity-55">可直接把图片文件或整个文件夹拖到此输入框</p>
    </div>
  );
}
