/**
 * Shared variable type helpers + schema shapes for flow.variable_schemas.
 */

export type VarType = 'string' | 'number' | 'boolean' | 'object' | 'array' | 'object_array';

export type FieldType = 'string' | 'number' | 'boolean';

export type VariableSchema = {
  type: VarType;
  /** object / object_array field definitions */
  fields?: Record<string, FieldType>;
  /** scalar array element type */
  itemType?: FieldType;
};

export const TYPE_LABELS: Record<VarType, string> = {
  string: '字符串',
  number: '数字',
  boolean: '布尔',
  object: '对象',
  array: '数组',
  object_array: '对象数组',
};

export const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  string: '字符串',
  number: '数字',
  boolean: '布尔',
};

export const COMPLEX_TYPES: VarType[] = ['object', 'array', 'object_array'];

export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

export function inferType(value: unknown): VarType {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value)) {
    if (value.length === 0) return 'array';
    if (value.every((item) => isPlainObject(item))) return 'object_array';
    return 'array';
  }
  if (isPlainObject(value)) return 'object';
  return 'string';
}

export function defaultValueFor(type: VarType): unknown {
  switch (type) {
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'object':
      return {};
    case 'array':
      return [];
    case 'object_array':
      return [{}];
    default:
      return '';
  }
}

export function defaultJsonText(type: VarType): string {
  switch (type) {
    case 'object':
      return '{\n  \n}';
    case 'array':
      return '[\n  \n]';
    case 'object_array':
      return '[\n  {\n    \n  }\n]';
    default:
      return '';
  }
}

export function toJsonText(value: unknown): string {
  try {
    return JSON.stringify(value ?? null, null, 2);
  } catch {
    return String(value ?? '');
  }
}

export function parseComplex(
  raw: string,
  type: VarType,
): { ok: true; value: unknown } | { ok: false; error: string } {
  const text = raw.trim() || (type === 'object' ? '{}' : '[]');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e: any) {
    return { ok: false, error: e?.message || 'JSON 格式错误' };
  }
  if (type === 'object') {
    if (!isPlainObject(parsed)) return { ok: false, error: '对象类型需要 { ... }' };
    return { ok: true, value: parsed };
  }
  if (!Array.isArray(parsed)) return { ok: false, error: '数组类型需要 [ ... ]' };
  if (type === 'object_array') {
    if (!parsed.every((item) => isPlainObject(item))) {
      return { ok: false, error: '对象数组的每一项都必须是对象 { ... }' };
    }
  }
  return { ok: true, value: parsed };
}

export function coerceScalar(
  raw: string,
  type: 'string' | 'number' | 'boolean',
): string | number | boolean {
  if (type === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  }
  if (type === 'boolean') return raw === 'true' || raw === '1';
  return raw;
}

export function convertValue(value: unknown, to: VarType): unknown {
  if (to === inferType(value)) return value;
  if (COMPLEX_TYPES.includes(to)) {
    if (to === 'object' && isPlainObject(value)) return value;
    if (to === 'array' && Array.isArray(value)) return value;
    if (to === 'object_array' && Array.isArray(value) && value.every(isPlainObject)) return value;
    if (typeof value === 'string') {
      const parsed = parseComplex(value, to);
      if (parsed.ok) return parsed.value;
    }
    return defaultValueFor(to);
  }
  if (to === 'boolean') return Boolean(value);
  if (to === 'number') {
    const n = Number(value as any);
    return Number.isFinite(n) ? n : 0;
  }
  if (COMPLEX_TYPES.includes(inferType(value))) return toJsonText(value);
  return String(value ?? '');
}

export function normalizeVarKey(name: string): string {
  let n = String(name || '').trim();
  if (!n) return '';
  if (!n.startsWith('$')) n = `$${n.replace(/^\$/, '')}`;
  return n;
}

export function lookupVariable(
  name: string,
  variables: Record<string, any> | undefined,
): unknown {
  if (!name || !variables) return undefined;
  const root = String(name).replace(/^\$/, '').split('.')[0];
  if (!root) return undefined;
  if (root in variables) return variables[root];
  if (`$${root}` in variables) return variables[`$${root}`];
  for (const k of Object.keys(variables)) {
    if (String(k).replace(/^\$/, '') === root) return variables[k];
  }
  return undefined;
}

export function lookupVariableSchema(
  name: string,
  schemas: Record<string, VariableSchema> | undefined,
): VariableSchema | undefined {
  if (!name || !schemas) return undefined;
  const root = String(name).replace(/^\$/, '').split('.')[0];
  if (!root) return undefined;
  if (root in schemas) return schemas[root];
  if (`$${root}` in schemas) return schemas[`$${root}`];
  for (const k of Object.keys(schemas)) {
    if (String(k).replace(/^\$/, '') === root) return schemas[k];
  }
  return undefined;
}

/** Dig into a value with dotted path (skip root name). */
export function digValue(root: unknown, pathParts: string[]): unknown {
  let cur: any = root;
  for (const part of pathParts) {
    if (cur == null) return undefined;
    if (Array.isArray(cur)) {
      if (!/^\d+$/.test(part)) return undefined;
      const idx = Number(part);
      if (idx < 0 || idx >= cur.length) return undefined;
      cur = cur[idx];
      continue;
    }
    if (isPlainObject(cur)) {
      if (part in cur) {
        cur = cur[part];
        continue;
      }
      return undefined;
    }
    return undefined;
  }
  return cur;
}

/**
 * Resolve `$name` or `$name.0.field` against variables.
 * Returns { found, value }.
 */
export function resolveVarPath(
  path: string,
  variables: Record<string, any> | undefined,
): { found: boolean; value?: unknown } {
  const raw = String(path || '').replace(/^\$/, '');
  if (!raw) return { found: false };
  const parts = raw.split('.').filter(Boolean);
  if (!parts.length) return { found: false };
  if (!validateRootExists(parts[0], variables)) return { found: false };
  const rootVal = lookupVariable(parts[0], variables);
  if (parts.length === 1) return { found: true, value: rootVal };
  let cur: any = rootVal;
  for (const part of parts.slice(1)) {
    if (cur == null) return { found: false };
    if (Array.isArray(cur)) {
      if (!/^\d+$/.test(part) || Number(part) < 0 || Number(part) >= cur.length) {
        return { found: false };
      }
      cur = cur[Number(part)];
    } else if (isPlainObject(cur)) {
      if (!(part in cur)) return { found: false };
      cur = cur[part];
    } else {
      return { found: false };
    }
  }
  return { found: true, value: cur };
}

function validateRootExists(root: string, variables?: Record<string, any>): boolean {
  if (!variables) return false;
  if (root in variables || `$${root}` in variables) return true;
  return Object.keys(variables).some((k) => String(k).replace(/^\$/, '') === root);
}

export function inferLeafType(value: unknown): string {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value)) return 'array';
  if (isPlainObject(value)) return 'object';
  if (value === null || value === undefined) return 'any';
  return 'string';
}

/** Prefer schema field types along a path; fall back to runtime value type. */
export function resolveVarPathType(
  path: string,
  variables: Record<string, any> | undefined,
  schemas?: Record<string, VariableSchema>,
): string {
  const raw = String(path || '').replace(/^\$/, '');
  const parts = raw.split('.').filter(Boolean);
  if (!parts.length) return 'any';
  const schema = lookupVariableSchema(parts[0], schemas);
  if (schema) {
    if (parts.length === 1) return schema.type === 'object_array' ? 'array' : schema.type;
    if (schema.type === 'array' && parts.length === 2 && /^\d+$/.test(parts[1])) {
      return schema.itemType || 'any';
    }
    if (schema.type === 'object' && parts.length === 2 && schema.fields?.[parts[1]]) {
      return schema.fields[parts[1]];
    }
    if (schema.type === 'object_array') {
      // $arr.0.field
      if (parts.length >= 2 && /^\d+$/.test(parts[1])) {
        if (parts.length === 2) return 'object';
        if (parts.length === 3 && schema.fields?.[parts[2]]) return schema.fields[parts[2]];
      }
    }
  }
  const resolved = resolveVarPath(path, variables);
  if (!resolved.found) return 'any';
  return inferLeafType(resolved.value);
}

export function defaultSchemaFor(type: VarType, value?: unknown): VariableSchema {
  if (type === 'object' && isPlainObject(value)) {
    const fields: Record<string, FieldType> = {};
    for (const [k, v] of Object.entries(value)) {
      const t = inferLeafType(v);
      if (t === 'string' || t === 'number' || t === 'boolean') fields[k] = t;
      else fields[k] = 'string';
    }
    return { type, fields };
  }
  if (type === 'object_array' && Array.isArray(value)) {
    const fields: Record<string, FieldType> = {};
    for (const row of value) {
      if (!isPlainObject(row)) continue;
      for (const [k, v] of Object.entries(row)) {
        if (fields[k]) continue;
        const t = inferLeafType(v);
        fields[k] = t === 'string' || t === 'number' || t === 'boolean' ? t : 'string';
      }
    }
    return { type, fields };
  }
  if (type === 'array') {
    let itemType: FieldType = 'string';
    if (Array.isArray(value) && value.length) {
      const t = inferLeafType(value[0]);
      if (t === 'number' || t === 'boolean' || t === 'string') itemType = t;
    }
    return { type, itemType };
  }
  return { type };
}

export function typeHint(type: VarType, name: string): string {
  const ref = name.startsWith('$') ? name : `$${name}`;
  if (type === 'object') return `引用整对象 ${ref}，或字段 ${ref}.field`;
  if (type === 'array') return `引用整数组 ${ref}，或元素 ${ref}.0`;
  if (type === 'object_array') return `引用整表 ${ref}，或 ${ref}.0.name`;
  return `引用: ${ref}`;
}
