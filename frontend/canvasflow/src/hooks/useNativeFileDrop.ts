/**
 * Native OS file-drop path plumbing.
 *
 * WebView2 的 HTML5 drop 事件不带真实文件路径；pywebview 在原生侧补全
 * （backend/main.py 注册 document 级 drop 监听），经 UI 事件队列以
 * `native_file_drop` 运行时事件转发，App.tsx 再以 window 自定义事件
 * `nexuz-native-file-drop` 分发到这里。
 *
 * 想接收 OS 拖放的输入框：dragover / drop 时调用 armNativeDropTarget
 * 挂上回调（原生事件在 DOM drop 之后异步到达，靠 TTL 兜底自动解除），
 * dragleave 离开字段时 disarm。同一时间只有一个目标接收本次拖放。
 */

type DropHandler = (paths: string[]) => void;

let armedHandler: DropHandler | null = null;
let disarmTimer: number | undefined;
let listening = false;

function ensureListener() {
  if (listening || typeof window === 'undefined') return;
  listening = true;
  window.addEventListener('nexuz-native-file-drop', (e) => {
    const handler = armedHandler;
    if (!handler) return;
    const detail = (e as CustomEvent).detail;
    const paths = Array.isArray(detail)
      ? detail.map(p => String(p || '').trim()).filter(Boolean)
      : [];
    disarmNativeDropTarget();
    if (paths.length) handler(paths);
  });
}

export function disarmNativeDropTarget() {
  armedHandler = null;
  if (disarmTimer !== undefined) {
    window.clearTimeout(disarmTimer);
    disarmTimer = undefined;
  }
}

export function armNativeDropTarget(handler: DropHandler, ttlMs = 4000): () => void {
  ensureListener();
  armedHandler = handler;
  if (disarmTimer !== undefined) window.clearTimeout(disarmTimer);
  disarmTimer = window.setTimeout(() => {
    armedHandler = null;
    disarmTimer = undefined;
  }, ttlMs);
  return () => {
    if (armedHandler === handler) disarmNativeDropTarget();
  };
}

/** 把一次拖入的多个路径归约为单个输入值。 */
export function pickDropValue(paths: string[]): string | null {
  const unique = [...new Set(paths.map(p => String(p || '').trim()).filter(Boolean))];
  if (unique.length === 0) return null;
  if (unique.length === 1) return unique[0];
  // 多个文件且同目录 → 取该目录（正好走节点的批量模式）；否则取第一个
  const parentOf = (p: string) => p.replace(/[\\/][^\\/]*$/, '');
  const norm = (s: string) => s.toLowerCase().replace(/\//g, '\\');
  const parents = unique.map(parentOf);
  if (parents.every(p => norm(p) === norm(parents[0]))) return parents[0];
  return unique[0];
}
