/**
 * Param binding helpers: literal | {{nodeId.field}} | {{nodeId.matches.0.x}} | $var
 */
export type BindKind = 'literal' | 'node' | 'variable';

/** field may include dotted path / numeric segments after the root output name */
const NODE_REF_RE = /^\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\s*\}\}$/;
const VAR_REF_RE = /^\$([A-Za-z_][A-Za-z0-9_]*)$/;
const VAR_BRACE_RE = /^\{\{\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$/;

export function isRefValue(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const s = value.trim();
  return NODE_REF_RE.test(s) || VAR_REF_RE.test(s) || VAR_BRACE_RE.test(s);
}

export function detectBindKind(value: unknown): BindKind {
  if (typeof value !== 'string') return 'literal';
  const s = value.trim();
  if (NODE_REF_RE.test(s)) return 'node';
  if (VAR_REF_RE.test(s) || VAR_BRACE_RE.test(s)) return 'variable';
  return 'literal';
}

export function parseNodeRef(value: string): { nodeId: string; field: string } | null {
  const m = NODE_REF_RE.exec(String(value || '').trim());
  if (!m) return null;
  return { nodeId: m[1], field: m[2] };
}

/** Root schema output name for a possibly nested field path (matches.0.x → matches) */
export function rootFieldName(field: string): string {
  const s = String(field || '');
  const i = s.indexOf('.');
  return i >= 0 ? s.slice(0, i) : s;
}

export function parseVarRef(value: string): string | null {
  const s = String(value || '').trim();
  let m = VAR_REF_RE.exec(s);
  if (m) return m[1];
  m = VAR_BRACE_RE.exec(s);
  return m ? m[1] : null;
}

export function formatNodeRef(nodeId: string, field: string): string {
  return `{{${nodeId}.${field}}}`;
}

export function formatVarRef(name: string): string {
  const n = String(name || '').replace(/^\$/, '').trim();
  return n ? `$${n}` : '';
}

/** Normalize flow.variables keys → bare names without $, deduped & sorted */
export function listFlowVariableNames(variables: Record<string, any> | undefined | null): string[] {
  const keys = new Set<string>();
  for (const k of Object.keys(variables || {})) {
    const bare = String(k).replace(/^\$/, '').trim();
    if (bare) keys.add(bare);
  }
  return Array.from(keys).sort((a, b) => a.localeCompare(b));
}

export function literalToDisplay(value: unknown, inputType?: string): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** Parse user-typed literal back to number when input is number and not a ref */
export function coerceLiteral(raw: string, inputType?: string): string | number {
  const s = String(raw ?? '');
  if (isRefValue(s)) return s.trim();
  if (inputType === 'number') {
    if (s.trim() === '') return 0;
    const n = Number(s);
    return Number.isFinite(n) ? n : s;
  }
  return s;
}

export function isBindableInput(input: {
  type?: string;
  bindable?: boolean;
  name?: string;
  ui?: string;
}): boolean {
  if (input.bindable === false) return false;
  if (input.ui === 'expression') return false;
  if (input.type === 'keymap' || input.ui === 'input_map' || input.ui === 'output_map') return false;
  if (input.type === 'condition_list' || input.type === 'cases' || input.type === 'logic_tree')
    return false;
  if (input.bindable === true) return true;
  const t = input.type || 'string';
  return t === 'number' || t === 'string' || t === 'color';
}
