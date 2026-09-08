"""browser_snapshot：可交互元素快照 + ref 定位体系。

用法：browser_snapshot 产出 ref 表（e1..eN）→ browser_click / browser_fill
按 ref 定位，免去手写 CSS 选择器。ref 是快照时间点的定位映射（绝对 CSS
路径），页面结构变化后可能失效——失效时报错提示重新快照。
"""

from __future__ import annotations

from backend.blocks._browser import call_engine

# 可交互元素收集器：为每个元素生成稳定定位（优先 #id，否则
# tag:nth-of-type 链），只保留可见（非零尺寸）元素。
_SNAPSHOT_JS = """
(() => {
  const MAX = __MAX__;
  const sel = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="menuitem"], [onclick], [tabindex]';
  const nodes = Array.from(document.querySelectorAll(sel)).slice(0, MAX);
  const path = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement && parts.length < 12) {
      let seg = cur.tagName.toLowerCase();
      if (cur.id) { parts.unshift('#' + CSS.escape(cur.id)); break; }
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) seg += ':nth-of-type(' + (same.indexOf(cur) + 1) + ')';
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.length ? parts.join(' > ') : el.tagName.toLowerCase();
  };
  return {
    url: location.href,
    title: document.title,
    items: nodes.map(el => {
      const r = el.getBoundingClientRect();
      const rec = {
        selector: path(el),
        tag: el.tagName.toLowerCase(),
        text: ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().slice(0, 120),
        placeholder: el.getAttribute ? el.getAttribute('placeholder') : null,
        value: ('value' in el) ? String(el.value ?? '').slice(0, 120) : null,
        href: el.getAttribute ? el.getAttribute('href') : null,
        rect: {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)},
      };
      const role = el.getAttribute && el.getAttribute('role');
      if (role) rec.role = role;
      if (el.disabled) rec.disabled = true;
      return rec;
    }).filter(r => r.rect.width > 0 && r.rect.height > 0),
  };
})()
"""

_MAX_ELEMENTS_DEFAULT = 200
# ref 缓存按引擎实例分桶；引擎重建后 id 变化自然失效，桶数上限防泄漏。
_REF_BUCKETS_MAX = 8
_REFS: dict[int, dict[str, str]] = {}


def _bucket(eng) -> dict[str, str]:
    if len(_REFS) >= _REF_BUCKETS_MAX and id(eng) not in _REFS:
        _REFS.pop(next(iter(_REFS)))
    return _REFS.setdefault(id(eng), {})


def clear_refs(eng) -> None:
    """页签导航/引擎关闭后由其他积木调用，使快照 ref 全部失效。"""
    _REFS.pop(id(eng), None)


def resolve_ref(eng, ref) -> str:
    """ref → 快照时的 CSS 定位；空 ref 原样返回。"""
    ref = str(ref or "").strip()
    if not ref:
        return ""
    selector = _REFS.get(id(eng), {}).get(ref)
    if not selector:
        from backend.core.browser.errors import BrowserError

        raise BrowserError(f"ref {ref} 不在当前快照中或已失效，请先执行 browser_snapshot")
    return selector


SCHEMA = {
    "type": "browser_snapshot",
    "label": "浏览器快照",
    "category": "浏览器",
    "description": "收集页面可交互元素生成 ref 表（e1..eN，含 tag/文本/占位/矩形与定位），供 browser_click/browser_fill 按 ref 操作，免去手写选择器。",
    "inputs": [
        {
            "name": "max_elements",
            "type": "number",
            "label": "元素上限",
            "default": _MAX_ELEMENTS_DEFAULT,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "url", "type": "string"},
        {"name": "title", "type": "string"},
        {"name": "elements", "type": "array", "itemType": "object", "canvas": False},
        {"name": "count", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    try:
        max_elements = int(params.get("max_elements") or _MAX_ELEMENTS_DEFAULT)
    except (TypeError, ValueError):
        max_elements = _MAX_ELEMENTS_DEFAULT
    max_elements = max(1, min(max_elements, 1000))

    def op(eng):
        data = eng.eval_js(_SNAPSHOT_JS.replace("__MAX__", str(max_elements)), timeout_ms=15000)
        if not isinstance(data, dict):
            from backend.core.browser.errors import BrowserError

            raise BrowserError("快照失败：页面返回异常")
        refs = _bucket(eng)
        refs.clear()
        elements: list[dict] = []
        for i, item in enumerate(data.get("items") or [], 1):
            if not isinstance(item, dict):
                continue
            selector = str(item.get("selector") or "")
            if not selector:
                continue
            rect = item.get("rect") or {}
            try:
                if float(rect.get("width") or 0) <= 0 or float(rect.get("height") or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            ref = f"e{len(elements) + 1}"
            refs[ref] = selector
            elements.append(
                {
                    "ref": ref,
                    "tag": item.get("tag"),
                    "role": item.get("role"),
                    "text": item.get("text"),
                    "placeholder": item.get("placeholder"),
                    "value": item.get("value"),
                    "href": item.get("href"),
                    "rect": rect,
                }
            )
        return {
            "url": str(data.get("url") or ""),
            "title": str(data.get("title") or ""),
            "elements": elements,
            "count": len(elements),
        }

    return call_engine(op)
