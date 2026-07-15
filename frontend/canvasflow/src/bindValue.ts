/**
 * Param binding helpers: literal | {{nodeId.field}} | {{nodeId.matches.0.x}} | $var | $var.0.x
 */
export type BindKind = 'literal' | 'node' | 'variable';

/** field may include dotted path / numeric segments after the root output name */
const NODE_REF_RE = /^\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\s*\}\}$/;
/** $name or $name.0.field */
const VAR_REF_RE = /^\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)$/;
const VAR_BRACE_RE = /^\{\{\s*\$?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}$/;

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

/**
 * Parse `$users.0.name` / `{{$users.0.name}}` / `{{users.0.name}}`
 * → bare path without leading $ : `users.0.name`
 */
export function parseVarRef(value: string): string | null {
  const s = String(value || '').trim();
  let m = VAR_REF_RE.exec(s);
  if (m) return m[1];
  m = VAR_BRACE_RE.exec(s);
  return m ? m[1] : null;
}

/** Split `users.0.name` → { root: 'users', path: '0.name' } */
export function splitVarPath(full: string): { root: string; path: string } {
  const s = String(full || '')
    .replace(/^\$/, '')
    .trim();
  const i = s.indexOf('.');
  if (i < 0) return { root: s, path: '' };
  return { root: s.slice(0, i), path: s.slice(i + 1) };
}

export function formatNodeRef(nodeId: string, field: string): string {
  return `{{${nodeId}.${field}}}`;
}

/** Build `$name` or `$name.0.field` */
export function formatVarRef(name: string, path?: string): string {
  const n = String(name || '')
    .replace(/^\$/, '')
    .trim();
  if (!n) return '';
  const p = String(path || '')
    .replace(/^\./, '')
    .trim();
  return p ? `$${n}.${p}` : `$${n}`;
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

export function lookupFlowVariable(
  variables: Record<string, any> | undefined | null,
  bare: string,
): unknown {
  const name = String(bare || '')
    .replace(/^\$/, '')
    .trim();
  if (!name) return undefined;
  const vars = variables || {};
  if (name in vars) return vars[name];
  if (`$${name}` in vars) return vars[`$${name}`];
  return undefined;
}

/** Flatten object/array into relative path suggestions (maxDepth). */
export function listValuePaths(value: unknown, maxDepth = 3, prefix = ''): string[] {
  if (maxDepth < 0 || value == null) return prefix ? [prefix] : [];
  const out: string[] = [];
  if (prefix) out.push(prefix);

  if (Array.isArray(value)) {
    const n = Math.min(value.length, 8);
    for (let i = 0; i < n; i++) {
      const next = prefix ? `${prefix}.${i}` : String(i);
      out.push(...listValuePaths(value[i], maxDepth - 1, next));
    }
    return Array.from(new Set(out));
  }
  if (typeof value === 'object') {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (!/^[A-Za-z0-9_]+$/.test(k)) continue;
      const next = prefix ? `${prefix}.${k}` : k;
      out.push(...listValuePaths(v, maxDepth - 1, next));
    }
    return Array.from(new Set(out));
  }
  return out;
}

export function literalToDisplay(value: unknown, inputType?: string): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Parse user-typed literal; JSON object/array when allowJson and text looks like JSON. */
export function coerceLiteral(
  raw: string,
  inputType?: string,
  allowJson = false,
): string | number | boolean | object | any[] {
  const s = String(raw ?? '');
  if (isRefValue(s)) return s.trim();
  if (allowJson) {
    const t = s.trim();
    if ((t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))) {
      try {
        return JSON.parse(t);
      } catch {
        /* keep as string */
      }
    }
  }
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
  if (input.type === 'point_list' || input.type === 'key_steps') return false;
  if (input.type === 'keys' || input.type === 'rect' || input.type === 'select') return false;
  if (input.bindable === true) return true;
  const t = input.type || 'string';
  // Scalars + whole array/object bindings (path dig via NodeOutputFieldSelect / VariableSelect)
  return (
    t === 'number' ||
    t === 'string' ||
    t === 'color' ||
    t === 'boolean' ||
    t === 'bool' ||
    t === 'any' ||
    t === 'array' ||
    t === 'object' ||
    t === 'textarea'
  );
}
