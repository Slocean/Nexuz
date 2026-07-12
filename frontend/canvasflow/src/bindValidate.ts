/**
 * Validate {{node.field}} / $var bindings against current flow + schemas.
 */
import {
  detectBindKind,
  parseNodeRef,
  parseVarRef,
} from './bindValue';
import { collectParamRefs } from './nexuzAdapter';

export type BindIssueLevel = 'error' | 'warn';

export type BindIssue = {
  level: BindIssueLevel;
  nodeId: string;
  paramName?: string;
  message: string;
  /** For canvas data-edge matching */
  sourceId?: string;
  field?: string;
};

const EMBEDDED_NODE_REF = /\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*\}\}/g;
const EMBEDDED_VAR_REF = /\$([A-Za-z_][A-Za-z0-9_]*)/g;

/** Normalize schema/output types for compatibility checks */
export function normalizeType(t?: string): string {
  const s = String(t || 'any').toLowerCase();
  if (s === 'int' || s === 'float' || s === 'integer') return 'number';
  if (s === 'bool') return 'boolean';
  if (s === 'color') return 'string';
  if (s === 'text' || s === 'str') return 'string';
  return s || 'any';
}

/**
 * true = compatible; false = likely mismatch (warn only, still runnable).
 * any ↔ * always ok; number↔boolean warn; string accepts most.
 */
export function typesCompatible(sourceType?: string, targetType?: string): boolean {
  const s = normalizeType(sourceType);
  const t = normalizeType(targetType);
  if (s === 'any' || t === 'any') return true;
  if (s === t) return true;
  // string can hold serialized anything
  if (t === 'string') return true;
  // number ↔ boolean is suspicious
  if ((s === 'number' && t === 'boolean') || (s === 'boolean' && t === 'number')) return false;
  // boolean → string already handled; number → string handled
  if (s === 'string' && (t === 'number' || t === 'boolean')) return false;
  return s === t;
}

export function lookupOutputType(
  nodeId: string,
  field: string,
  flowNodes: Record<string, any>,
  schemaMap: Record<string, any>,
): string | undefined {
  const node = flowNodes?.[nodeId];
  if (!node) return undefined;
  const outs = schemaMap[node.type]?.outputs;
  if (!Array.isArray(outs)) return undefined;
  const hit = outs.find((o: any) => o?.name === field);
  return hit?.type;
}

export function validateNodeRef(
  nodeId: string,
  field: string,
  flowNodes: Record<string, any>,
  schemaMap: Record<string, any>,
): { ok: true } | { ok: false; reason: 'missing_node' | 'missing_field' } {
  const node = flowNodes?.[nodeId];
  if (!node) return { ok: false, reason: 'missing_node' };
  const outs = schemaMap[node.type]?.outputs;
  if (!Array.isArray(outs) || outs.length === 0) {
    // No declared outputs — still allow (runtime may set keys), but treat missing schema as ok
    return { ok: true };
  }
  if (!outs.some((o: any) => o?.name === field)) {
    return { ok: false, reason: 'missing_field' };
  }
  return { ok: true };
}

export function validateVarRef(
  name: string,
  variables: Record<string, any> | undefined,
): boolean {
  if (!name) return false;
  const vars = variables || {};
  if (name in vars) return true;
  if (`$${name}` in vars) return true;
  // bare key without $
  for (const k of Object.keys(vars)) {
    if (String(k).replace(/^\$/, '') === name) return true;
  }
  return false;
}

export type SingleBindStatus = {
  broken: boolean;
  typeWarn: boolean;
  message?: string;
};

/** Status for a single param value (used by BindableInput) */
export function inspectBindValue(
  value: unknown,
  inputType: string | undefined,
  currentNodeId: string,
  flowNodes: Record<string, any>,
  schemaMap: Record<string, any>,
  variables: Record<string, any> | undefined,
): SingleBindStatus {
  const kind = detectBindKind(value);
  if (kind === 'literal' || typeof value !== 'string') {
    return { broken: false, typeWarn: false };
  }

  if (kind === 'variable') {
    const name = parseVarRef(value);
    if (!name) return { broken: true, typeWarn: false, message: '变量引用格式无效' };
    if (!validateVarRef(name, variables)) {
      return { broken: true, typeWarn: false, message: `变量 $${name} 未定义` };
    }
    return { broken: false, typeWarn: false };
  }

  const ref = parseNodeRef(value);
  if (!ref) return { broken: true, typeWarn: false, message: '上游引用格式无效' };
  if (ref.nodeId === currentNodeId) {
    return { broken: true, typeWarn: false, message: '不能引用自身输出' };
  }
  const vr = validateNodeRef(ref.nodeId, ref.field, flowNodes, schemaMap);
  if (!vr.ok) {
    return {
      broken: true,
      typeWarn: false,
      message:
        vr.reason === 'missing_node'
          ? `节点 ${ref.nodeId} 不存在`
          : `节点无输出字段 ${ref.field}`,
    };
  }

  const srcType = lookupOutputType(ref.nodeId, ref.field, flowNodes, schemaMap);
  if (inputType && srcType && !typesCompatible(srcType, inputType)) {
    return {
      broken: false,
      typeWarn: true,
      message: `类型可能不匹配：${srcType} → ${inputType}`,
    };
  }
  return { broken: false, typeWarn: false };
}

/** Scan expression / free text for embedded refs */
export function inspectEmbeddedRefs(
  text: string,
  currentNodeId: string,
  flowNodes: Record<string, any>,
  schemaMap: Record<string, any>,
  variables?: Record<string, any>,
): BindIssue[] {
  const issues: BindIssue[] = [];
  if (!text || typeof text !== 'string') return issues;

  let m: RegExpExecArray | null;
  const nodeRe = new RegExp(EMBEDDED_NODE_REF.source, 'g');
  while ((m = nodeRe.exec(text))) {
    const nodeId = m[1];
    const field = m[2];
    if (nodeId === currentNodeId) {
      issues.push({
        level: 'error',
        nodeId: currentNodeId,
        message: `表达式引用了自身 ${nodeId}.${field}`,
        sourceId: nodeId,
        field,
      });
      continue;
    }
    const vr = validateNodeRef(nodeId, field, flowNodes, schemaMap);
    if (!vr.ok) {
      issues.push({
        level: 'error',
        nodeId: currentNodeId,
        message:
          vr.reason === 'missing_node'
            ? `引用的节点不存在: ${nodeId}`
            : `引用的字段不存在: ${nodeId}.${field}`,
        sourceId: nodeId,
        field,
      });
    }
  }

  const varRe = new RegExp(EMBEDDED_VAR_REF.source, 'g');
  while ((m = varRe.exec(text))) {
    const name = m[1];
    if (variables && !validateVarRef(name, variables)) {
      issues.push({
        level: 'error',
        nodeId: currentNodeId,
        message: `变量 $${name} 未定义`,
      });
    }
  }
  return issues;
}

/** Collect all bind issues across the flow */
export function collectFlowBindIssues(
  flow: any,
  schemaMap: Record<string, any>,
): BindIssue[] {
  const issues: BindIssue[] = [];
  const nodes = flow?.nodes || {};
  const variables = flow?.variables || {};
  const nodeIdSet = new Set(Object.keys(nodes));

  for (const [nodeId, node] of Object.entries(nodes) as [string, any][]) {
    const schema = schemaMap[node?.type] || {};
    const inputs: any[] = Array.isArray(schema.inputs) ? schema.inputs : [];
    const params = node?.params || {};

    for (const input of inputs) {
      const name = input?.name;
      if (!name) continue;
      const val = params[name];
      if (val == null) continue;

      if (input.ui === 'expression' || name === 'expression' || name === 'exit_condition') {
        for (const iss of inspectEmbeddedRefs(
          String(val),
          nodeId,
          nodes,
          schemaMap,
          variables,
        )) {
          issues.push({ ...iss, paramName: name });
        }
        continue;
      }

      const status = inspectBindValue(
        val,
        input.type,
        nodeId,
        nodes,
        schemaMap,
        variables,
      );
      if (status.broken) {
        const ref = typeof val === 'string' ? parseNodeRef(val) : null;
        issues.push({
          level: 'error',
          nodeId,
          paramName: name,
          message: `${input.label || name}: ${status.message}`,
          sourceId: ref?.nodeId,
          field: ref?.field,
        });
      } else if (status.typeWarn) {
        const ref = typeof val === 'string' ? parseNodeRef(val) : null;
        issues.push({
          level: 'warn',
          nodeId,
          paramName: name,
          message: `${input.label || name}: ${status.message}`,
          sourceId: ref?.nodeId,
          field: ref?.field,
        });
      }
    }

    // Also catch exact refs on params not in schema / nested keymap values
    for (const ref of collectParamRefs(params)) {
      if (!nodeIdSet.has(ref.sourceId)) {
        const already = issues.some(
          (i) =>
            i.nodeId === nodeId &&
            i.sourceId === ref.sourceId &&
            i.field === ref.field &&
            i.level === 'error',
        );
        if (!already) {
          issues.push({
            level: 'error',
            nodeId,
            paramName: ref.paramName,
            message: `引用的节点不存在: ${ref.sourceId}`,
            sourceId: ref.sourceId,
            field: ref.field,
          });
        }
      }
    }

    // input_map / output_map on call_subflow
    if (node?.type === 'call_subflow') {
      const inputMap = params.input_map;
      if (inputMap && typeof inputMap === 'object') {
        for (const [k, v] of Object.entries(inputMap)) {
          const status = inspectBindValue(
            v,
            'string',
            nodeId,
            nodes,
            schemaMap,
            variables,
          );
          if (status.broken) {
            issues.push({
              level: 'error',
              nodeId,
              paramName: `input_map.${k}`,
              message: `传入 ${k}: ${status.message}`,
            });
          }
        }
      }
    }
  }

  return issues;
}

/** Issues for one data connection edge */
export function issueForDataEdge(
  sourceId: string,
  field: string,
  targetId: string,
  paramName: string | undefined,
  issues: BindIssue[],
): BindIssue | undefined {
  return issues.find(
    (i) =>
      i.nodeId === targetId &&
      i.sourceId === sourceId &&
      i.field === field &&
      (paramName ? i.paramName === paramName || i.paramName?.endsWith(`.${paramName}`) : true),
  );
}
