/**
 * Template / anchor image path field:
 * - bindable path input
 * - capture template (截模板)
 * - pick from folder
 * - paste image / drag-drop image → saved into data_dir/templates/
 * - preview current path (hover / dialog)
 */
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Eye, FolderOpen, ImagePlus } from 'lucide-react';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import BindableInput, { ImagePreviewButton, looksLikeImagePath } from './BindableInput';
import { useAppDialog } from './AppDialogs';

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取图片失败'));
    reader.readAsDataURL(file);
  });
}

function isImageFile(file: File | null | undefined): file is File {
  if (!file) return false;
  if (file.type && file.type.startsWith('image/')) return true;
  return /\.(png|jpe?g|bmp|webp|gif)$/i.test(file.name || '');
}

export default function TemplateImageField({
  value,
  onChange,
  currentNodeId,
  schemaMap,
  onCaptureTemplate,
  pickMethod,
  placeholder = '模板 PNG 路径',
}: {
  value: any;
  onChange: (next: any) => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
  onCaptureTemplate?: (method?: string) => Promise<any>;
  pickMethod?: string;
  placeholder?: string;
}) {
  const { alert } = useAppDialog();
  const dropRef = useRef<HTMLDivElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const pathValue = useMemo(() => {
    const raw = typeof value === 'string' ? value.trim() : '';
    return looksLikeImagePath(raw) ? raw : '';
  }, [value]);

  const applyPath = useCallback(
    (path: string) => {
      const p = String(path || '').trim();
      if (p) onChange(p);
    },
    [onChange],
  );

  const importFile = useCallback(
    async (file: File) => {
      if (!isImageFile(file)) {
        await alert({ title: '不支持的文件', description: '请使用 PNG / JPG / BMP / WEBP / GIF 图片' });
        return;
      }
      setBusy(true);
      try {
        const dataUrl = await fileToDataUrl(file);
        const res = await bridge.saveTemplateImage(dataUrl, file.name || null);
        if (!res?.ok) {
          await alert({ title: '导入失败', description: res?.error || '无法保存模板图片' });
          return;
        }
        applyPath(String(res.path));
      } catch (e: any) {
        await alert({ title: '导入失败', description: String(e?.message || e) });
      } finally {
        setBusy(false);
      }
    },
    [alert, applyPath],
  );

  const onPaste = useCallback(
    async (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items?.length) return;
      for (const item of Array.from(items)) {
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (!file) continue;
          e.preventDefault();
          e.stopPropagation();
          await importFile(file);
          return;
        }
      }
      // Also accept image files listed on clipboardData.files
      const files = e.clipboardData?.files;
      if (files?.length) {
        for (const file of Array.from(files)) {
          if (isImageFile(file)) {
            e.preventDefault();
            e.stopPropagation();
            await importFile(file);
            return;
          }
        }
      }
    },
    [importFile],
  );

  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      const files = e.dataTransfer?.files;
      if (!files?.length) return;
      const file = Array.from(files).find(isImageFile);
      if (!file) {
        await alert({ title: '未识别到图片', description: '请拖入图片文件' });
        return;
      }
      await importFile(file);
    },
    [alert, importFile],
  );

  const pickFromFolder = async () => {
    setBusy(true);
    try {
      const res = await bridge.pickTemplateImage();
      if (res?.cancelled) return;
      if (!res?.ok) {
        await alert({ title: '选择失败', description: res?.error || '无法选择图片' });
        return;
      }
      applyPath(String(res.path));
    } catch (e: any) {
      await alert({ title: '选择失败', description: String(e?.message || e) });
    } finally {
      setBusy(false);
    }
  };

  const capture = async () => {
    if (!onCaptureTemplate) return;
    setBusy(true);
    try {
      const res = await onCaptureTemplate(pickMethod);
      if (res?.ok && res.path) applyPath(String(res.path));
      else if (res && res.cancelled !== true && res?.error) {
        await alert({ title: '截模板失败', description: String(res.error) });
      }
    } catch (e: any) {
      await alert({ title: '截模板失败', description: String(e?.message || e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 min-w-0 space-y-1.5">
      <div
        ref={dropRef}
        tabIndex={0}
        onPaste={onPaste}
        onDragEnter={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragOver(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          if (!dropRef.current?.contains(e.relatedTarget as Node)) setDragOver(false);
        }}
        onDrop={onDrop}
        className={`rounded-lg border border-dashed px-2 py-1.5 transition-colors outline-none focus-visible:ring-1 focus-visible:ring-[var(--primary)] ${
          dragOver
            ? 'border-[var(--primary)] bg-[var(--primary)]/10'
            : 'border-black/15 dark:border-white/15'
        }`}
        title="可粘贴图片、拖入图片，或点下方按钮选择"
      >
        <div className="flex items-center gap-1.5 min-w-0">
          <BindableInput
            value={value}
            inputType="string"
            currentNodeId={currentNodeId}
            schemaMap={schemaMap}
            onChange={onChange}
            placeholder={placeholder}
          />
        </div>
        <p className="mt-1 text-[10px] opacity-55 flex items-center gap-1">
          <ImagePlus className="w-3 h-3 shrink-0" />
          {busy ? '处理中…' : dragOver ? '松开以导入图片' : '点击此处后 Ctrl+V 粘贴，或拖入图片'}
        </p>
      </div>
      <div className="flex flex-wrap gap-1">
        {onCaptureTemplate && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 shrink-0 px-2"
            disabled={busy}
            onClick={() => void capture()}
          >
            截模板
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 shrink-0 px-2 gap-1"
          disabled={busy}
          onClick={() => void pickFromFolder()}
          title="从文件夹选择图片"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          选择图片
        </Button>
        {pathValue ? (
          <ImagePreviewButton
            path={pathValue}
            disabled={busy}
            label={
              <>
                <Eye className="w-3.5 h-3.5 inline-block mr-1 -mt-0.5" />
                预览
              </>
            }
            className="inline-flex items-center h-8 shrink-0 px-2 text-xs rounded-md border border-input bg-background hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          />
        ) : null}
      </div>
    </div>
  );
}
