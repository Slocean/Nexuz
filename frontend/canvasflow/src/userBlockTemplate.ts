/** Default source for a new user block (.py under user_blocks). */
export const USER_BLOCK_STARTER = `SCHEMA = {
    "type": "my_block",
    "label": "我的积木",
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
`;

export function stemToBlockType(stem: string): string {
  const s = String(stem || '')
    .trim()
    .replace(/\.py$/i, '')
    .replace(/[^A-Za-z0-9_]/g, '_')
    .replace(/^_+/, '');
  return s || 'my_block';
}

export function starterForFilename(filename: string): string {
  const stem = stemToBlockType(filename);
  return USER_BLOCK_STARTER.replace(/my_block/g, stem).replace(
    /我的积木/g,
    stem,
  );
}
