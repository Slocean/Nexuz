import React, { useEffect, useMemo, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link2, Hash } from 'lucide-react';
import { useFlowStore } from '@/store/flowModelStore';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  BindKind,
  coerceLiteral,
  detectBindKind,
  formatNodeRef,
  formatVarRef,
  isRefValue,
  listFlowVariableNames,
  literalToDisplay,
  parseNodeRef,
} from '../bindValue';
import { inspectBindValue } from '../bindValidate';
import VariableSelect from './VariableSelect';
import { bridge } from '@/bridge';

type SchemaMap = Record<string, { label?: string; outputs?: { name: string; type?: string }[] }>;

interface BindableInputProps {
  value: unknown;
  inputType?: string; // number | string | color
  placeholder?: string;
  currentNodeId: string;
  schemaMap: SchemaMap;
  onChange: (value: unknown) => void;
  /** Extra trailing controls (e.g. 取点) */
  trailing?: React.ReactNode;
  className?: string;
  /** Allow JSON object/array as literal (赋值节点等) */
  allowJson?: boolean;
}

function Row({
  title,
  children,
  trailing,
}: {
  title: string;
  children: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 min-w-0 w-full">
      <span className="text-[11px] font-medium opacity-60 leading-none">{title}</span>
      <div className="flex items-center gap-1.5 min-w-0 w-full">
        <div className="flex-1 min-w-0">{children}</div>
        {trailing}
      </div>
    </div>
  );
}

export default function BindableInput({
  value,
  inputType = 'string',
  placeholder,
  currentNodeId,
  schemaMap,
  onChange,
  trailing,
  className,
  allowJson = false,
}: BindableInputProps) {
  const flowNodes = useFlowStore((s) => s.flow.nodes || {});
  const variables = useFlowStore((s) => s.flow.variables || {});
  const variableSchemas = useFlowStore((s) => s.flow.variable_schemas || {});

  const kind = detectBindKind(value);
  const nodeRef = kind === 'node' && typeof value === 'string' ? parseNodeRef(value) : null;
  const isJsonLiteral =
    allowJson &&
    kind === 'literal' &&
    (Array.isArray(value) || (!!value && typeof value === 'object'));

  const [jsonDraft, setJsonDraft] = useState(() => literalToDisplay(value, inputType));
  const [jsonError, setJsonError] = useState<string | null>(null);
  useEffect(() => {
    if (isJsonLiteral || (allowJson && kind === 'literal')) {
      setJsonDraft(literalToDisplay(value, inputType));
      setJsonError(null);
    }
  }, [value, isJsonLiteral, allowJson, kind, inputType]);

  const status = useMemo(
    () =>
      inspectBindValue(
        value,
        inputType,
        currentNodeId,
        flowNodes,
        schemaMap,
        variables,
        variableSchemas,
      ),
    [value, inputType, currentNodeId, flowNodes, schemaMap, variables, variableSchemas],
  );

  const nodeOptions = useMemo(() => {
    return Object.entries(flowNodes)
      .filter(([id]) => id !== currentNodeId)
      .map(([id, node]: [string, any]) => {
        const schema = schemaMap[node?.type] || {};
        const outputs = Array.isArray(schema.outputs) ? schema.outputs : [];
        const label = node?.name || schema.label || node?.type || id;
        return { id, label, type: node?.type, outputs };
      })
      .filter((n) => n.outputs.length > 0);
  }, [flowNodes, schemaMap, currentNodeId]);

  const hasUpstream = nodeOptions.length > 0;
  const varOptions = useMemo(() => listFlowVariableNames(variables), [variables]);

  const selectedNode = nodeOptions.find((n) => n.id === nodeRef?.nodeId);
  const fields = selectedNode?.outputs || [];

  useEffect(() => {
    if (!hasUpstream && kind === 'node') {
      onChange(inputType === 'number' ? 0 : '');
    }
    // only react when upstream availability flips while kind is node
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUpstream]);

  const setKind = (next: BindKind) => {
    if (next === 'literal') {
      onChange(allowJson ? '' : inputType === 'number' ? 0 : '');
      return;
    }
    if (next === 'variable') {
      const first = varOptions[0];
      onChange(first ? formatVarRef(first) : '');
      return;
    }
    if (!hasUpstream) return;
    const first = nodeOptions[0];
    const field = first?.outputs?.[0]?.name;
    if (first && field) onChange(formatNodeRef(first.id, field));
    else onChange('{{node.field}}');
  };

  const commitJson = () => {
    const t = jsonDraft.trim();
    if (!t) {
      onChange('');
      setJsonError(null);
      return;
    }
    try {
      const parsed = JSON.parse(t);
      onChange(parsed);
      setJsonError(null);
    } catch (e: any) {
      // still try coerceLiteral for refs / plain text
      const coerced = coerceLiteral(jsonDraft, inputType, true);
      if (typeof coerced === 'object') {
        onChange(coerced);
        setJsonError(null);
      } else if (isRefValue(jsonDraft)) {
        onChange(String(jsonDraft).trim());
        setJsonError(null);
      } else {
        setJsonError(e?.message || 'JSON 无效');
      }
    }
  };

  return (
    <div className={`flex flex-col gap-2 min-w-0 flex-1 w-full ${className || ''}`}>
      <div
        className={`flex flex-col gap-2 min-w-0 w-full ${
          status.broken
            ? 'rounded-md ring-1 ring-rose-500/60 p-1.5'
            : status.typeWarn
              ? 'rounded-md ring-1 ring-amber-500/50 p-1.5'
              : ''
        }`}
        title={status.message || undefined}
      >
        <Row title="类型">
          <Select
            value={kind === 'node' && !hasUpstream ? 'literal' : kind}
            onValueChange={(v) => setKind(v as BindKind)}
          >
            <SelectTrigger className="h-8 w-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="literal">常量</SelectItem>
              <SelectItem value="node" disabled={!hasUpstream}>
                上游{!hasUpstream ? '（无可用节点）' : ''}
              </SelectItem>
              <SelectItem value="variable" disabled={varOptions.length === 0}>
                变量{varOptions.length === 0 ? '（未创建）' : ''}
              </SelectItem>
            </SelectContent>
          </Select>
        </Row>

        {kind === 'literal' || (kind === 'node' && !hasUpstream) ? (
          <Row title={allowJson ? '值（支持 JSON）' : '值'} trailing={trailing}>
            {allowJson ? (
              <div className="space-y-1 w-full">
                <Textarea
                  className="text-xs font-mono min-h-[4.5rem] resize-y w-full"
                  value={jsonDraft}
                  placeholder={placeholder || '文本，或 {"a":1} / [1,2]'}
                  onChange={(e) => {
                    setJsonDraft(e.target.value);
                    setJsonError(null);
                  }}
                  onBlur={commitJson}
                />
                {jsonError ? <p className="text-[11px] text-rose-500">{jsonError}</p> : null}
              </div>
            ) : (
              <Input
                type="text"
                inputMode={inputType === 'number' ? 'decimal' : undefined}
                className="h-8 w-full"
                value={literalToDisplay(value, inputType)}
                placeholder={placeholder || (inputType === 'number' ? '数值' : '文本')}
                onChange={(e) => onChange(coerceLiteral(e.target.value, inputType))}
              />
            )}
          </Row>
        ) : kind === 'variable' ? (
          <Row title="变量" trailing={trailing}>
            <VariableSelect
              value={value}
              onChange={onChange}
              allowPath
              placeholder={varOptions.length ? '选择已创建变量' : '暂无变量'}
            />
          </Row>
        ) : (
          <>
            <Row title="上游节点">
              <Select
                value={nodeRef?.nodeId || undefined}
                onValueChange={(nid) => {
                  const n = nodeOptions.find((x) => x.id === nid);
                  const field = n?.outputs?.[0]?.name || 'value';
                  onChange(formatNodeRef(nid, field));
                }}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue placeholder={hasUpstream ? '选择节点' : '无上游输出'} />
                </SelectTrigger>
                <SelectContent>
                  {nodeOptions.length === 0 ? (
                    <SelectItem value="__none" disabled>
                      无带输出的节点
                    </SelectItem>
                  ) : (
                    nodeOptions.map((n) => (
                      <SelectItem key={n.id} value={n.id}>
                        {n.label}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </Row>
            <Row title="输出字段" trailing={trailing}>
              <Select
                value={nodeRef?.field || undefined}
                onValueChange={(field) => {
                  const nid = nodeRef?.nodeId || nodeOptions[0]?.id;
                  if (!nid) return;
                  onChange(formatNodeRef(nid, field));
                }}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue placeholder="选择字段" />
                </SelectTrigger>
                <SelectContent>
                  {fields.length === 0 ? (
                    <SelectItem value="__none" disabled>
                      —
                    </SelectItem>
                  ) : (
                    fields.map((f) => (
                      <SelectItem key={f.name} value={f.name}>
                        {f.name}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </Row>
            {typeof value === 'string' && isRefValue(value) && (
              <p className="text-[10px] font-mono opacity-45 truncate" title={value}>
                {value}
              </p>
            )}
          </>
        )}
      </div>
      {status.message && (status.broken || status.typeWarn) && (
        <p
          className={`text-[11px] leading-tight pl-0.5 ${
            status.broken ? 'text-rose-500' : 'text-amber-600 dark:text-amber-400'
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

function looksLikeImagePath(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const p = value.trim();
  if (!p) return false;
  return /\.(png|jpe?g|bmp|webp|gif)$/i.test(p);
}

function useLocalImage(path: string | null, enabled: boolean) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !path) {
      setDataUrl(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await bridge.readLocalImage(path);
        if (cancelled) return;
        if (res?.ok && res.data_url) setDataUrl(String(res.data_url));
        else setError(res?.error || '无法加载预览');
      } catch (e: any) {
        if (!cancelled) setError(String(e?.message || e || '预览失败'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [path, enabled]);

  return { dataUrl, error, loading };
}

/** Wheel zoom + drag pan image stage for the preview dialog. */
function ZoomPanImage({ src, alt }: { src: string; alt: string }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [grabbing, setGrabbing] = useState(false);
  const dragging = useRef(false);
  const last = useRef({ x: 0, y: 0 });
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setGrabbing(false);
  }, [src]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.12 : 0.12;
      setScale((s) => Math.min(8, Math.max(0.2, Number((s + delta * Math.max(s, 0.5)).toFixed(3)))));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    dragging.current = true;
    setGrabbing(true);
    last.current = { x: e.clientX, y: e.clientY };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dx = e.clientX - last.current.x;
    const dy = e.clientY - last.current.y;
    last.current = { x: e.clientX, y: e.clientY };
    setOffset((o) => ({ x: o.x + dx, y: o.y + dy }));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragging.current = false;
    setGrabbing(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="relative w-full h-full min-h-0 flex flex-col">
      <div
        ref={stageRef}
        className={`relative flex-1 min-h-0 overflow-hidden rounded-lg bg-black/10 dark:bg-black/50 select-none touch-none ${
          grabbing ? 'cursor-grabbing' : 'cursor-grab'
        }`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => {
          setScale(1);
          setOffset({ x: 0, y: 0 });
        }}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="absolute left-1/2 top-1/2 max-w-none pointer-events-none"
          style={{
            transform: `translate(calc(-50% + ${offset.x}px), calc(-50% + ${offset.y}px)) scale(${scale})`,
            transformOrigin: 'center center',
          }}
        />
      </div>
      <div className="flex items-center justify-between gap-2 pt-2 shrink-0">
        <p className="text-[11px] opacity-50">滚轮缩放 · 拖动平移 · 双击复位</p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => setScale((s) => Math.max(0.2, Number((s / 1.2).toFixed(3))))}
          >
            −
          </button>
          <span className="text-[11px] font-mono opacity-60 w-12 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => setScale((s) => Math.min(8, Number((s * 1.2).toFixed(3))))}
          >
            +
          </button>
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => {
              setScale(1);
              setOffset({ x: 0, y: 0 });
            }}
          >
            复位
          </button>
        </div>
      </div>
    </div>
  );
}

/** Image path shown as link: hover thumbnail above, click opens dialog. */
function ImagePathLink({ path }: { path: string }) {
  const linkRef = useRef<HTMLAnchorElement | null>(null);
  const [hover, setHover] = useState(false);
  const [open, setOpen] = useState(false);
  const [tipPos, setTipPos] = useState<{ left: number; top: number } | null>(null);
  const wantLoad = hover || open;
  const { dataUrl, error, loading } = useLocalImage(path, wantLoad);

  const updateTipPos = () => {
    const el = linkRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const tipW = 200;
    const tipH = 150;
    let left = r.left;
    let top = r.top - tipH - 10;
    if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
    if (left < 8) left = 8;
    if (top < 8) top = r.bottom + 8;
    setTipPos({ left, top });
  };

  return (
    <>
      <a
        ref={linkRef}
        href="#"
        className="font-mono text-xs text-blue-500 underline underline-offset-2 break-all whitespace-pre-wrap text-left hover:text-blue-400"
        title="悬停预览，点击放大"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
        onMouseEnter={() => {
          updateTipPos();
          setHover(true);
        }}
        onMouseLeave={() => setHover(false)}
        onMouseMove={updateTipPos}
      >
        {path}
      </a>
      {hover &&
        tipPos &&
        createPortal(
          <div
            className="fixed z-[220] pointer-events-none rounded-lg border border-black/15 dark:border-white/15 bg-zinc-950/95 shadow-xl p-1.5"
            style={{ left: tipPos.left, top: tipPos.top, width: 200 }}
          >
            <div className="flex items-center justify-center h-[130px] bg-black/40 rounded-md overflow-hidden">
              {loading ? (
                <span className="text-[10px] text-zinc-400">加载中…</span>
              ) : error ? (
                <span className="text-[10px] text-rose-400 px-1 text-center">{error}</span>
              ) : dataUrl ? (
                <img
                  src={dataUrl}
                  alt="缩略图"
                  className="max-w-full max-h-[130px] object-contain"
                  draggable={false}
                />
              ) : null}
            </div>
          </div>,
          document.body,
        )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[min(96vw,88rem)] w-[min(96vw,88rem)] h-[min(92vh,56rem)] p-4 flex flex-col gap-3">
          <DialogHeader className="shrink-0">
            <DialogTitle className="text-sm">图片预览</DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 flex flex-col">
            {loading && !dataUrl ? (
              <div className="flex-1 flex items-center justify-center rounded-lg bg-black/5 dark:bg-black/40">
                <p className="text-xs opacity-50">加载中…</p>
              </div>
            ) : error && !dataUrl ? (
              <div className="flex-1 flex items-center justify-center rounded-lg bg-black/5 dark:bg-black/40">
                <p className="text-xs text-rose-400 break-all px-2">{error}</p>
              </div>
            ) : dataUrl ? (
              <ZoomPanImage src={dataUrl} alt="预览" />
            ) : null}
          </div>
          <p className="text-[11px] font-mono opacity-60 break-all select-text shrink-0">{path}</p>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Compact chip showing a copyable output ref */
export function OutputRefChip({
  nodeId,
  field,
  value,
  onCopied,
}: {
  nodeId: string;
  field: string;
  value?: unknown;
  onCopied?: () => void;
}) {
  const ref = formatNodeRef(nodeId, field);
  const isImage = looksLikeImagePath(value);
  const display =
    value === undefined
      ? '—'
      : typeof value === 'object'
        ? JSON.stringify(value)
        : String(value);
  const copy = async () => {
    try {
      const res = await bridge.clipboardWrite(ref);
      if (res?.ok) {
        onCopied?.();
        return;
      }
    } catch {
      /* fall through */
    }
    try {
      await navigator.clipboard.writeText(ref);
      onCopied?.();
    } catch {
      /* ignore */
    }
  };
  return (
    <div className="flex items-start gap-1.5 w-full min-w-0 rounded-lg px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors group">
      <button
        type="button"
        onClick={copy}
        title={`点击复制 ${ref}`}
        className="flex items-start gap-1.5 shrink-0 text-left"
      >
        <Hash className="w-3 h-3 opacity-40 shrink-0 mt-0.5" />
        <span className="font-mono text-xs font-medium shrink-0 mt-0.5">{field}</span>
      </button>
      <div className="flex-1 min-w-0">
        {isImage ? (
          <ImagePathLink path={String(value)} />
        ) : (
          <button
            type="button"
            onClick={copy}
            title={`点击复制 ${ref}`}
            className="font-mono text-xs opacity-50 flex-1 min-w-0 break-all whitespace-pre-wrap text-left w-full"
          >
            {display}
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={copy}
        title={`点击复制 ${ref}`}
        className="shrink-0 mt-0.5"
      >
        <Link2 className="w-3 h-3 opacity-0 group-hover:opacity-60" />
      </button>
    </div>
  );
}
