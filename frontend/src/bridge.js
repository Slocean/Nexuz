/** Bridge to pywebview Python API with browser fallbacks for Vite-only dev. */

function getApi() {
  return window.pywebview?.api ?? null;
}

export function waitForBridge(timeoutMs = 10000) {
  return new Promise((resolve) => {
    if (getApi()) {
      resolve(getApi());
      return;
    }
    const start = Date.now();
    const timer = setInterval(() => {
      if (getApi()) {
        clearInterval(timer);
        resolve(getApi());
      } else if (Date.now() - start > timeoutMs) {
        clearInterval(timer);
        resolve(null);
      }
    }, 50);
  });
}

export const MOCK_SCHEMAS = [
  {
    type: 'click',
    label: '鼠标点击',
    category: '动作类',
    inputs: [
      {
        name: 'click_mode',
        type: 'select',
        label: '模式',
        options: ['single', 'multi'],
        default: 'single',
        option_labels: { single: '单点', multi: '多点' },
      },
      {
        name: 'capture_mode',
        type: 'select',
        label: '录入模式',
        options: ['coord', 'frida_ui'],
        default: 'coord',
      },
      {
        name: 'coordinate_mode',
        type: 'select',
        label: '坐标基准',
        options: ['screen_abs', 'window_client', 'virtual_norm'],
        default: 'screen_abs',
        option_labels: {
          screen_abs: '屏幕绝对坐标',
          window_client: '目标窗口相对（推荐）',
          virtual_norm: '虚拟桌面比例',
        },
        show_when: { capture_mode: 'coord' },
      },
      { name: 'x', type: 'number', label: 'X', default: 0, show_when: { click_mode: 'single' } },
      { name: 'y', type: 'number', label: 'Y', default: 0, show_when: { click_mode: 'single' } },
      {
        name: 'points',
        type: 'point_list',
        label: '点击点',
        default: [],
        bindable: false,
        show_when: { click_mode: 'multi' },
      },
      {
        name: 'interval_ms',
        type: 'number',
        label: '点间延迟毫秒',
        default: 200,
        show_when: { click_mode: 'multi' },
        placeholder: '相邻两点间隔',
      },
      { name: 'button', type: 'select', label: '按键', options: ['left', 'right', 'middle'], default: 'left' },
      { name: 'click_type', type: 'select', label: '点击类型', options: ['single', 'double'], default: 'single' },
      {
        name: 'move_duration',
        type: 'number',
        label: '移动耗时毫秒',
        default: 0,
        show_when: { click_mode: 'single' },
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'button', type: 'string' },
      { name: 'count', type: 'number' },
    ],
  },
  {
    type: 'delay',
    label: '延时',
    category: '动作类',
    inputs: [{ name: 'ms', type: 'number', label: '毫秒', default: 500 }],
    outputs: [],
  },
  {
    type: 'key_press',
    label: '按键',
    category: '动作类',
    inputs: [
      {
        name: 'key_mode',
        type: 'select',
        label: '模式',
        options: ['single', 'sequence'],
        default: 'single',
        option_labels: { single: '单次', sequence: '序列' },
      },
      {
        name: 'keys',
        type: 'keys',
        label: '按键',
        default: ['enter'],
        placeholder: '点击录制',
        show_when: { key_mode: 'single' },
      },
      {
        name: 'steps',
        type: 'key_steps',
        label: '按键序列',
        default: [],
        bindable: false,
        show_when: { key_mode: 'sequence' },
      },
      {
        name: 'interval_ms',
        type: 'number',
        label: '步间延迟毫秒',
        default: 100,
        show_when: { key_mode: 'sequence' },
        placeholder: '相邻两步间隔',
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'count', type: 'number' },
    ],
  },
  {
    type: 'mouse_scroll',
    label: '鼠标滚轮',
    category: '动作类',
    inputs: [
      { name: 'x', type: 'number', label: '焦点X', default: 0 },
      { name: 'y', type: 'number', label: '焦点Y', default: 0 },
      {
        name: 'move_first',
        type: 'select',
        label: '先移到焦点',
        options: ['true', 'false'],
        default: 'true',
        option_labels: { true: '是（推荐）', false: '否（当前位置滚）' },
      },
      {
        name: 'direction',
        type: 'select',
        label: '方向',
        options: ['up', 'down', 'left', 'right'],
        default: 'down',
        option_labels: { up: '向上', down: '向下', left: '向左', right: '向右' },
      },
      { name: 'clicks', type: 'number', label: '滚动量', default: 3 },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'amount', type: 'number' },
    ],
  },
  {
    type: 'type_text',
    label: '输入文本',
    category: '动作类',
    inputs: [
      { name: 'text', type: 'string', label: '文本', default: '' },
      { name: 'interval', type: 'number', label: '字符间隔毫秒', default: 0 },
    ],
    outputs: [],
  },
  {
    type: 'drag',
    label: '鼠标拖拽',
    category: '动作类',
    inputs: [
      { name: 'from_x', type: 'number', label: '起点X', default: 0 },
      { name: 'from_y', type: 'number', label: '起点Y', default: 0 },
      { name: 'to_x', type: 'number', label: '终点X', default: 0 },
      { name: 'to_y', type: 'number', label: '终点Y', default: 0 },
      { name: 'duration', type: 'number', label: '耗时毫秒', default: 300 },
    ],
    outputs: [
      { name: 'from_x', type: 'number' },
      { name: 'from_y', type: 'number' },
      { name: 'to_x', type: 'number' },
      { name: 'to_y', type: 'number' },
    ],
  },
  {
    type: 'mouse_hover',
    label: '鼠标悬停',
    category: '动作类',
    inputs: [
      {
        name: 'hover_mode',
        type: 'select',
        label: '模式',
        options: ['single', 'multi'],
        default: 'single',
        option_labels: { single: '单点', multi: '多点' },
      },
      { name: 'x', type: 'number', label: 'X', default: 0, show_when: { hover_mode: 'single' } },
      { name: 'y', type: 'number', label: 'Y', default: 0, show_when: { hover_mode: 'single' } },
      {
        name: 'points',
        type: 'point_list',
        label: '悬停点',
        default: [],
        bindable: false,
        show_when: { hover_mode: 'multi' },
      },
      {
        name: 'interval_ms',
        type: 'number',
        label: '点间延迟毫秒',
        default: 200,
        show_when: { hover_mode: 'multi' },
        placeholder: '相邻两点间隔',
      },
      { name: 'move_duration', type: 'number', label: '移动耗时毫秒', default: 0 },
      {
        name: 'hold_ms',
        type: 'number',
        label: '悬停毫秒',
        default: 300,
        placeholder: '到达后停留',
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'count', type: 'number' },
    ],
  },
  {
    type: 'color_detect',
    label: '取色',
    category: '识别类',
    inputs: [
      {
        name: 'sample_mode',
        type: 'select',
        label: '模式',
        options: ['point', 'region', 'multi'],
        default: 'point',
        option_labels: {
          point: '单点',
          region: '区域',
          multi: '多点',
          single: '单点',
        },
      },
      {
        name: 'x',
        type: 'number',
        label: 'X',
        default: 0,
        show_when: { sample_mode: ['point', 'single'] },
      },
      {
        name: 'y',
        type: 'number',
        label: 'Y',
        default: 0,
        show_when: { sample_mode: ['point', 'single'] },
      },
      {
        name: 'region',
        type: 'rect',
        label: '区域',
        default: null,
        show_when: { sample_mode: 'region' },
      },
      {
        name: 'points',
        type: 'point_list',
        label: '取色点',
        default: [],
        bindable: false,
        show_when: { sample_mode: 'multi' },
      },
    ],
    outputs: [
      { name: 'color', type: 'string' },
      { name: 'colors', type: 'array', canvas: false },
      { name: 'count', type: 'number' },
    ],
  },
  {
    type: 'if_color_match',
    label: '颜色匹配',
    category: '识别类',
    inputs: [
      {
        name: 'source_mode',
        type: 'select',
        label: '数据来源',
        options: ['capture', 'value'],
        default: 'capture',
        option_labels: { capture: '现场取色', value: '上游颜色' },
      },
      {
        name: 'actual_color',
        type: 'string',
        label: '实际颜色',
        default: '',
        show_when: { source_mode: 'value' },
      },
      { name: 'x', type: 'number', label: 'X', default: 0, show_when: { source_mode: 'capture' } },
      { name: 'y', type: 'number', label: 'Y', default: 0, show_when: { source_mode: 'capture' } },
      {
        name: 'region',
        type: 'rect',
        label: '区域',
        default: null,
        show_when: { source_mode: 'capture' },
      },
      { name: 'target_color', type: 'color', label: '目标颜色', default: '#FF0000' },
      { name: 'tolerance', type: 'number', label: '容差', default: 10 },
    ],
    outputs: [
      { name: 'matched', type: 'boolean' },
      { name: 'color', type: 'string' },
    ],
  },
  {
    type: 'if_condition',
    label: '条件分支',
    category: '控制类',
    inputs: [
      {
        name: 'expression',
        type: 'string',
        label: '表达式',
        default: '',
        bindable: false,
        ui: 'expression',
      },
    ],
    outputs: [{ name: 'matched', type: 'boolean' }],
  },
  {
    type: 'if_logic',
    label: '组合条件',
    category: '控制类',
    inputs: [
      {
        name: 'logic',
        type: 'logic_tree',
        label: '条件树',
        default: {
          kind: 'group',
          id: 'root',
          op: 'and',
          not: false,
          children: [{ kind: 'expr', id: 'c0', expression: '', not: false, label: '' }],
        },
        bindable: false,
      },
    ],
    outputs: [
      { name: 'matched', type: 'boolean' },
      { name: 'matched_count', type: 'number' },
      { name: 'total', type: 'number' },
    ],
  },
  {
    type: 'switch',
    label: '多分支',
    category: '控制类',
    inputs: [
      { name: 'variable', type: 'string', label: '判断值', default: '' },
      {
        name: 'cases',
        type: 'cases',
        label: '分支',
        default: [],
        description: '每条分支可设比较方式（等于/包含/大于等），自上而下首次命中即跳转',
      },
      { name: 'default', type: 'string', label: '默认分支', default: '', bindable: false, placeholder: '未匹配时跳转' },
    ],
    outputs: [{ name: 'value', type: 'string' }],
  },
  {
    type: 'loop_n',
    label: '固定次数循环',
    category: '控制类',
    inputs: [{ name: 'times', type: 'number', label: '次数', default: 3 }],
    outputs: [{ name: 'index', type: 'number' }],
  },
  {
    type: 'loop_foreach',
    label: '按数组循环',
    category: '控制类',
    inputs: [
      {
        name: 'collection',
        type: 'string',
        label: '数组',
        default: '',
        placeholder: '$items 或 {{node.list}}',
      },
      {
        name: 'item_var',
        type: 'string',
        label: '当前项变量名',
        default: '$item',
        bindable: false,
        placeholder: '$item',
      },
    ],
    outputs: [
      { name: 'index', type: 'number' },
      { name: 'item', type: 'any', canvas: false },
      { name: 'length', type: 'number' },
    ],
  },
  {
    type: 'loop_while',
    label: '条件循环',
    category: '控制类',
    inputs: [
      {
        name: 'expression',
        type: 'string',
        label: '继续条件',
        default: '',
        bindable: false,
        ui: 'expression',
      },
      { name: 'max_times', type: 'number', label: '最大次数', default: 10000 },
    ],
    outputs: [{ name: 'matched', type: 'boolean' }],
  },
  {
    type: 'loop_forever',
    label: '无限循环',
    category: '控制类',
    inputs: [
      {
        name: 'exit_condition',
        type: 'string',
        label: '退出条件',
        default: '',
        bindable: false,
        ui: 'expression',
      },
      { name: 'check_interval_ms', type: 'number', label: '每轮间隔毫秒', default: 200 },
      { name: 'max_times', type: 'number', label: '安全最大次数', default: 1000000 },
    ],
    outputs: [],
  },
  {
    type: 'ocr_recognize',
    label: 'OCR取字',
    category: '识别类',
    inputs: [
      { name: 'region', type: 'rect', label: '识别区域', default: null },
      { name: 'x', type: 'number', label: '起点 X', default: 0 },
      { name: 'y', type: 'number', label: '起点 Y', default: 0 },
      { name: 'width', type: 'number', label: '宽度', default: 320 },
      { name: 'height', type: 'number', label: '高度', default: 80 },
      { name: 'anchor_template', type: 'string', label: '锚点模板', default: '' },
      { name: 'anchor_threshold', type: 'number', label: '锚点阈值', default: 0.8 },
      { name: 'anchor_offset_x', type: 'number', label: '锚点偏移 X', default: 0 },
      { name: 'anchor_offset_y', type: 'number', label: '锚点偏移 Y', default: 0 },
      { name: 'anchor_ocr_width', type: 'number', label: '识别宽度', default: 0 },
      { name: 'anchor_ocr_height', type: 'number', label: '识别高度', default: 0 },
      { name: 'lang', type: 'select', label: '语言', options: ['auto', 'ch', 'en'], default: 'auto' },
      { name: 'min_confidence', type: 'number', label: '最低置信度', default: 0.3 },
      {
        name: 'match_text',
        type: 'string',
        label: '匹配文字',
        default: '',
      },
      {
        name: 'match_texts',
        type: 'string',
        label: '匹配多字',
        default: '',
        bindable: false,
        ui: 'textarea',
        placeholder: '匹配值一\n匹配值二\n...',
      },
      {
        name: 'match_mode',
        type: 'select',
        label: '匹配模式',
        options: ['contains', 'exact', 'regex'],
        default: 'contains',
        option_labels: { contains: '包含', exact: '完全相等', regex: '正则' },
      },
      {
        name: 'include_box_geometry',
        type: 'select',
        label: '保留多边形',
        options: ['false', 'true'],
        default: 'false',
        option_labels: {
          false: '否',
          true: '是',
        },
      },
    ],
    outputs: [
      { name: 'found', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
      { name: 'matched_text', type: 'string' },
      { name: 'text', type: 'string' },
      { name: 'confidence', type: 'number' },
      { name: 'matches', type: 'array', canvas: false },
      { name: 'boxes', type: 'array', canvas: false },
      { name: 'region', type: 'object', canvas: false },
      { name: 'anchor', type: 'object', canvas: false },
    ],
  },
  {
    type: 'locate_text',
    label: '文字定位',
    category: '识别类',
    inputs: [
      {
        name: 'boxes',
        type: 'string',
        label: 'boxes',
        default: '',
        bindable: true,
        placeholder: '{{ocr节点.boxes}}',
      },
      { name: 'match_text', type: 'string', label: '匹配文字', default: '', placeholder: '要找的字' },
      {
        name: 'match_mode',
        type: 'select',
        label: '匹配模式',
        options: ['contains', 'exact', 'regex'],
        default: 'contains',
        option_labels: { contains: '包含', exact: '完全相等', regex: '正则' },
      },
    ],
    outputs: [
      { name: 'found', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
      { name: 'matched_text', type: 'string' },
    ],
  },
  {
    type: 'if_text_contains',
    label: '文字匹配',
    category: '识别类',
    inputs: [
      {
        name: 'source_mode',
        type: 'select',
        label: '数据来源',
        options: ['capture', 'value'],
        default: 'capture',
        option_labels: { capture: '现场 OCR', value: '上游文本' },
      },
      {
        name: 'actual_text',
        type: 'string',
        label: '实际文本',
        default: '',
        show_when: { source_mode: 'value' },
      },
      {
        name: 'region',
        type: 'rect',
        label: '识别区域',
        default: null,
        show_when: { source_mode: 'capture' },
      },
      {
        name: 'x',
        type: 'number',
        label: '起点 X',
        default: 0,
        show_when: { source_mode: 'capture' },
      },
      {
        name: 'y',
        type: 'number',
        label: '起点 Y',
        default: 0,
        show_when: { source_mode: 'capture' },
      },
      {
        name: 'width',
        type: 'number',
        label: '宽度',
        default: 320,
        show_when: { source_mode: 'capture' },
      },
      {
        name: 'height',
        type: 'number',
        label: '高度',
        default: 80,
        show_when: { source_mode: 'capture' },
      },
      { name: 'expect_text', type: 'string', label: '期望文字', default: '' },
      {
        name: 'match_mode',
        type: 'select',
        label: '匹配模式',
        options: ['contains', 'exact', 'regex'],
        default: 'contains',
      },
      {
        name: 'lang',
        type: 'select',
        label: '语言',
        options: ['auto', 'ch', 'en'],
        default: 'auto',
        show_when: { source_mode: 'capture' },
      },
      {
        name: 'min_confidence',
        type: 'number',
        label: '最低置信度',
        default: 0.3,
        show_when: { source_mode: 'capture' },
      },
    ],
    outputs: [
      { name: 'matched', type: 'boolean' },
      { name: 'actual_text', type: 'string' },
      { name: 'found', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
      { name: 'matched_text', type: 'string' },
    ],
  },
  {
    type: 'find_image',
    label: '图像模板匹配',
    category: '识别类',
    inputs: [
      { name: 'template_image', type: 'string', label: '模板图片', default: '' },
      { name: 'search_region', type: 'rect', label: '搜索区域', default: null },
      { name: 'threshold', type: 'number', label: '相似度阈值', default: 0.8 },
    ],
    outputs: [
      { name: 'found', type: 'boolean' },
      { name: 'score', type: 'number' },
      { name: 'path', type: 'string' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
    ],
  },
  {
    type: 'screenshot',
    label: '区域截图',
    category: '识别类',
    inputs: [
      { name: 'region', type: 'rect', label: '截图区域', default: null },
      { name: 'save_path', type: 'string', label: '保存路径', default: '' },
    ],
    outputs: [
      { name: 'path', type: 'string' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
    ],
  },
  {
    type: 'wait_until',
    label: '条件等待',
    category: '动作类',
    inputs: [
      {
        name: 'wait_type',
        type: 'select',
        label: '等待类型',
        options: ['color', 'text', 'expression'],
        default: 'text',
        option_labels: {
          color: '颜色出现',
          text: '文字出现',
          expression: '表达式为真',
        },
      },
      {
        name: 'region',
        type: 'rect',
        label: '检测区域',
        default: null,
        show_when: { wait_type: ['color', 'text'] },
      },
      {
        name: 'x',
        type: 'number',
        label: '单点 X',
        default: 0,
        show_when: { wait_type: 'color' },
      },
      {
        name: 'y',
        type: 'number',
        label: '单点 Y',
        default: 0,
        show_when: { wait_type: 'color' },
      },
      {
        name: 'target_color',
        type: 'color',
        label: '目标颜色',
        default: '#FF0000',
        show_when: { wait_type: 'color' },
      },
      {
        name: 'tolerance',
        type: 'number',
        label: '颜色容差',
        default: 20,
        show_when: { wait_type: 'color' },
      },
      {
        name: 'expect_text',
        type: 'string',
        label: '期望文字',
        default: '',
        show_when: { wait_type: 'text' },
      },
      {
        name: 'match_mode',
        type: 'select',
        label: '匹配模式',
        options: ['contains', 'exact', 'regex'],
        default: 'contains',
        show_when: { wait_type: 'text' },
      },
      {
        name: 'expression',
        type: 'string',
        label: '表达式',
        default: '',
        bindable: false,
        ui: 'expression',
        show_when: { wait_type: 'expression' },
      },
      { name: 'timeout_ms', type: 'number', label: '超时毫秒', default: 30000 },
      { name: 'poll_interval_ms', type: 'number', label: '轮询间隔毫秒', default: 300 },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'elapsed_ms', type: 'number' },
      { name: 'detail', type: 'string' },
      { name: 'found', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'left', type: 'number' },
      { name: 'top', type: 'number' },
      { name: 'width', type: 'number' },
      { name: 'height', type: 'number' },
      { name: 'matched_text', type: 'string' },
    ],
  },
  {
    type: 'schedule_trigger',
    label: '注册定时任务',
    category: '控制类',
    description: '仅注册/更新定时任务，不会在此节点等待到点再继续。',
    inputs: [
      {
        name: 'trigger_type',
        type: 'select',
        label: '触发类型',
        options: ['interval', 'once', 'cron'],
        default: 'interval',
        option_labels: { interval: '周期', once: '单次', cron: 'Cron' },
      },
      {
        name: 'interval_seconds',
        type: 'number',
        label: '周期秒数',
        default: 60,
        show_when: { trigger_type: 'interval' },
      },
      {
        name: 'run_at',
        type: 'string',
        label: '单次时间',
        placeholder: '2026-07-12 10:00:00',
        default: '',
        show_when: { trigger_type: 'once' },
      },
      {
        name: 'cron_expression',
        type: 'string',
        label: 'Cron',
        default: '0 * * * *',
        placeholder: '分 时 日 月 周',
        show_when: { trigger_type: 'cron' },
      },
      {
        name: 'enabled',
        type: 'select',
        label: '启用',
        options: ['true', 'false'],
        default: 'true',
        option_labels: { true: '启用', false: '禁用' },
      },
    ],
    outputs: [
      { name: 'registered', type: 'boolean' },
      { name: 'job_id', type: 'string' },
    ],
  },
  {
    type: 'call_subflow',
    label: '调用子流程',
    category: '控制类',
    inputs: [
      {
        name: 'subflow_path',
        type: 'string',
        label: '子流程路径',
        default: '',
        placeholder: '选择或填写 .flow.json',
        ui: 'flow_path',
      },
      {
        name: 'inherit_variables',
        type: 'select',
        label: '继承父变量',
        options: ['true', 'false'],
        default: 'true',
        option_labels: {
          true: '是',
          false: '否',
        },
      },
      {
        name: 'input_map',
        type: 'keymap',
        label: '传入变量',
        default: {},
        ui: 'input_map',
      },
      {
        name: 'output_map',
        type: 'keymap',
        label: '取回变量',
        default: {},
        ui: 'output_map',
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'context_keys', type: 'number' },
      { name: 'keys', type: 'array', canvas: false },
    ],
  },
  {
    type: 'assign',
    label: '赋值变量',
    category: '控制类',
    inputs: [
      {
        name: 'mappings',
        type: 'keymap',
        label: '变量映射',
        default: {},
        ui: 'input_map',
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'written', type: 'array', canvas: false },
    ],
  },
];

async function call(method, ...args) {
  const api = getApi();
  if (!api || typeof api[method] !== 'function') {
    return mockCall(method, ...args);
  }
  try {
    const result = await api[method](...args);
    return result;
  } catch (e) {
    return {
      ok: false,
      error: String(e?.message || e || `${method} 调用失败`),
      message: String(e?.message || e || `${method} 调用失败`),
    };
  }
}

function mockCall(method, ...args) {
  switch (method) {
    case 'ping':
      return Promise.resolve({ ok: true, message: 'pong (browser mock)', dpi_scale: 1 });
    case 'get_app_info':
      return Promise.resolve({
        ok: true,
        version: '0.1.0-dev',
        frozen: false,
        github: 'Slocean/Nexuz',
        releases_url: 'https://github.com/Slocean/Nexuz/releases',
      });
    case 'check_for_update':
      return Promise.resolve({
        ok: true,
        update_available: false,
        current_version: '0.1.0-dev',
        latest_version: '0.1.0-dev',
        message: '浏览器预览：无法检查 GitHub 更新',
      });
    case 'fetch_announcement':
      return Promise.resolve({
        ok: true,
        announcement: {
          id: '0.1.0-dev',
          version: '0.1.0-dev',
          title: '浏览器预览',
          body: '更新记录预览。',
        },
        history: [
          {
            version: '0.1.0-dev',
            title: '浏览器预览',
            body: '更新记录预览。',
            notice: '这是通知说明预览。',
          },
        ],
        notice: {
          id: 'mock-notice',
          title: '通知',
          body: '这是通知说明预览。',
        },
      });
    case 'fetch_notice':
      return Promise.resolve({
        ok: true,
        notice: {
          id: 'mock-notice',
          title: '通知',
          body: '这是通知说明预览（桌面客户端中读取 app_update.json 的 notice 字段）。',
        },
      });
    case 'download_update':
    case 'apply_update':
      return Promise.resolve({ ok: false, error: '浏览器预览模式不支持热更新' });
    case 'open_releases_page':
      try {
        window.open('https://github.com/Slocean/Nexuz/releases', '_blank');
        return Promise.resolve({ ok: true });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    case 'get_block_registry':
      return Promise.resolve(MOCK_SCHEMAS);
    case 'list_schedule_jobs':
      return Promise.resolve({ ok: true, jobs: [] });
    case 'list_flows':
      return Promise.resolve({ ok: true, flows: [], dir: '', exists: false });
    case 'get_data_dir_info':
      return Promise.resolve({
        ok: true,
        path: 'localStorage/nexuz',
        exists: true,
        default_path: 'localStorage/nexuz',
        is_default: true,
      });
    case 'pick_data_dir':
    case 'set_data_dir_path':
    case 'open_data_dir':
    case 'clear_data_dir':
      return Promise.resolve({ ok: false, error: '浏览器预览模式不支持数据目录操作' });
    case 'clear_screenshot_cache':
      return Promise.resolve({ ok: true, deleted: 0, bytes: 0, message: '浏览器预览无截图缓存' });
    case 'export_flow': {
      try {
        const flow = typeof args[0] === 'string' ? JSON.parse(args[0]) : args[0];
        const name = String(args[1] || flow?.name || 'flow').trim() || 'flow';
        const blob = new Blob([JSON.stringify(flow, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name.endsWith('.flow.json') ? name : `${name}.flow.json`;
        a.click();
        URL.revokeObjectURL(url);
        return Promise.resolve({ ok: true, path: a.download, name: flow?.name });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    }
    case 'import_flow':
      return Promise.resolve({ ok: false, error: '浏览器预览请使用桌面客户端导入' });
    case 'pick_flow_file':
      return Promise.resolve({ ok: false, cancelled: true, error: '浏览器预览请手动填写路径' });
    case 'pick_template_image':
      return Promise.resolve({ ok: false, cancelled: true, error: '浏览器预览请手动填写路径或拖入图片' });
    case 'save_template_image':
      return Promise.resolve({ ok: false, error: '浏览器预览无法保存模板到数据目录，请用桌面客户端' });
    case 'list_flow_templates': {
      try {
        const raw = localStorage.getItem('nexuz.flowTemplates');
        const templates = raw ? JSON.parse(raw) : [];
        return Promise.resolve({ ok: true, templates: Array.isArray(templates) ? templates : [], dir: 'localStorage' });
      } catch {
        return Promise.resolve({ ok: true, templates: [], dir: 'localStorage' });
      }
    }
    case 'save_flow_template': {
      try {
        const flow = typeof args[0] === 'string' ? JSON.parse(args[0]) : args[0];
        const name = String(args[1] || flow?.name || '未命名模板').trim() || '未命名模板';
        const description = String(args[2] || flow?.description || '').trim();
        const item = {
          id: `local_${Date.now()}`,
          name,
          description,
          path: `local:${Date.now()}`,
          mtime: Date.now(),
          builtin: false,
          flow: { ...flow, name, description: description || undefined },
        };
        const raw = localStorage.getItem('nexuz.flowTemplates');
        const list = raw ? JSON.parse(raw) : [];
        const next = Array.isArray(list) ? list.filter((t) => t.name !== name) : [];
        next.unshift(item);
        localStorage.setItem('nexuz.flowTemplates', JSON.stringify(next));
        return Promise.resolve({ ok: true, path: item.path, name });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    }
    case 'delete_flow_template': {
      try {
        const filepath = String(args[0] || '');
        const raw = localStorage.getItem('nexuz.flowTemplates');
        const list = raw ? JSON.parse(raw) : [];
        const next = (Array.isArray(list) ? list : []).filter((t) => t.path !== filepath);
        localStorage.setItem('nexuz.flowTemplates', JSON.stringify(next));
        return Promise.resolve({ ok: true });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    }
    case 'load_flow_template': {
      try {
        const filepath = String(args[0] || '');
        const raw = localStorage.getItem('nexuz.flowTemplates');
        const list = raw ? JSON.parse(raw) : [];
        const hit = (Array.isArray(list) ? list : []).find((t) => t.path === filepath);
        if (!hit?.flow) return Promise.resolve({ ok: false, error: '模板不存在' });
        return Promise.resolve({ ok: true, flow: hit.flow, path: filepath });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    }
    case 'delete_flow':
      return Promise.resolve({ ok: false, error: '浏览器预览模式不支持' });
    case 'window_minimize':
    case 'window_toggle_maximize':
    case 'window_close':
    case 'window_is_maximized':
      return Promise.resolve({ ok: true, maximized: false });
    case 'window_toggle_on_top':
    case 'window_is_on_top':
      return Promise.resolve({ ok: true, on_top: false });
    case 'run_flow':
      return Promise.resolve({ ok: false, error: '请在桌面客户端中运行流程（python backend/main.py --dev）' });
    case 'save_flow':
    case 'load_flow':
    case 'read_local_image':
      return Promise.resolve({ ok: false, error: '浏览器预览模式不支持文件操作' });
    case 'clipboard_write':
      try {
        const t = args[0] ?? '';
        if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
          return navigator.clipboard.writeText(String(t)).then(() => ({ ok: true }));
        }
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
      return Promise.resolve({ ok: false, error: '剪贴板不可用' });
    case 'export_text':
      try {
        const text = String(args[0] ?? '');
        const name = String(args[1] || `nexuz-logs-${Date.now()}.txt`);
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.click();
        URL.revokeObjectURL(url);
        return Promise.resolve({ ok: true, path: name });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    case 'start_recording':
    case 'stop_recording':
    case 'pick_point':
    case 'pick_click':
    case 'pick_region':
    case 'capture_template':
    case 'capture_desktop':
    case 'pack_screen_point':
    case 'pack_screen_region':
    case 'capture_template_from_region':
    case 'list_capture_providers':
    case 'frida_attach':
    case 'frida_detach':
    case 'frida_status':
    case 'frida_list_processes':
    case 'pause_flow':
    case 'resume_flow':
    case 'continue_flow':
    case 'stop_flow':
    case 'force_reset':
    case 'step_flow':
    case 'set_breakpoints':
      return Promise.resolve({ ok: false, error: '浏览器预览模式不支持此操作' });
    case 'validate_flow':
      try {
        const raw = args[0];
        const flow = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (!flow || typeof flow !== 'object') {
          return Promise.resolve({ ok: false, error: '无效的流程对象' });
        }
        if (!flow.nodes || typeof flow.nodes !== 'object') {
          return Promise.resolve({ ok: false, error: '缺少 nodes 字段' });
        }
        return Promise.resolve({ ok: true });
      } catch (e) {
        return Promise.resolve({ ok: false, error: String(e) });
      }
    default:
      return Promise.resolve({ ok: false, error: `未知方法: ${method}` });
  }
}

export const bridge = {
  ping: () => call('ping'),
  getAppInfo: () => call('get_app_info'),
  checkForUpdate: () => call('check_for_update'),
  fetchAnnouncement: () => call('fetch_announcement'),
  fetchNotice: () => call('fetch_notice'),
  downloadUpdate: (downloadUrl = null) => call('download_update', downloadUrl),
  applyUpdate: () => call('apply_update'),
  openReleasesPage: () => call('open_releases_page'),
  getBlockRegistry: () => call('get_block_registry'),
  getScreenInfo: () => call('get_screen_info'),
  runFlow: (flow, stepMode = false, hideWindow = true, debugMode = false, breakpoints = null) =>
    call(
      'run_flow',
      JSON.stringify(flow),
      stepMode,
      hideWindow,
      debugMode,
      breakpoints ?? flow?.breakpoints ?? [],
    ),
  pauseFlow: () => call('pause_flow'),
  resumeFlow: () => call('resume_flow'),
  continueFlow: () => call('continue_flow'),
  stopFlow: () => call('stop_flow'),
  forceReset: () => call('force_reset'),
  stepFlow: () => call('step_flow'),
  setBreakpoints: (nodeIds) => call('set_breakpoints', nodeIds || []),
  isRunning: () => call('is_running'),
  validateFlow: (flow) => call('validate_flow', JSON.stringify(flow)),
  startRecording: (minIntervalMs = 50, hideWindow = false, mode = 'coord') =>
    call('start_recording', minIntervalMs, hideWindow, mode),
  stopRecording: () => call('stop_recording'),
  pickPoint: (hideWindow = true) => call('pick_point', hideWindow),
  pickClick: (mode = 'coord', hideWindow = true) => call('pick_click', mode, hideWindow),
  pickRegion: (hideWindow = true) => call('pick_region', hideWindow),
  captureTemplate: (hideWindow = true, filename = null) =>
    call('capture_template', hideWindow, filename),
  captureDesktop: (hideWindow = true) => call('capture_desktop', hideWindow),
  packScreenPoint: (x, y, color = null) => call('pack_screen_point', x, y, color),
  packScreenRegion: (region) => call('pack_screen_region', region),
  captureTemplateFromRegion: (region, filename = null, dataUrl = null, left = null, top = null) =>
    call('capture_template_from_region', region, filename, dataUrl, left, top),
  listCaptureProviders: () => call('list_capture_providers'),
  fridaAttach: (processNameOrOpts = null, pid = null) => {
    if (processNameOrOpts && typeof processNameOrOpts === 'object') {
      return call('frida_attach', processNameOrOpts);
    }
    return call('frida_attach', {
      process_name: processNameOrOpts,
      pid,
    });
  },
  fridaDetach: () => call('frida_detach'),
  fridaStatus: () => call('frida_status'),
  fridaListProcesses: (query = null, onlyWithWindow = true) =>
    call('frida_list_processes', {
      query,
      only_with_window: onlyWithWindow !== false,
    }),
  listScheduleJobs: () => call('list_schedule_jobs'),
  removeScheduleJob: (jobId) => call('remove_schedule_job', jobId),
  listFlows: () => call('list_flows'),
  pickFlowFile: () => call('pick_flow_file'),
  deleteFlow: (filepath) => call('delete_flow', filepath),
  renameFlow: (filepath, newName) => call('rename_flow', filepath, newName),
  saveFlow: (flow, filepath = null, name = null) =>
    call('save_flow', JSON.stringify(flow), filepath, name),
  loadFlow: (filepath = null) => call('load_flow', filepath),
  exportFlow: (flow, filename = null) =>
    call('export_flow', JSON.stringify(flow), filename),
  importFlow: () => call('import_flow'),
  getDataDirInfo: () => call('get_data_dir_info'),
  pickDataDir: () => call('pick_data_dir'),
  setDataDirPath: (path = null) => call('set_data_dir_path', path),
  openDataDir: () => call('open_data_dir'),
  clearDataDir: () => call('clear_data_dir'),
  clearScreenshotCache: () => call('clear_screenshot_cache'),
  listFlowTemplates: () => call('list_flow_templates'),
  saveFlowTemplate: (flow, name = null, description = null) =>
    call('save_flow_template', JSON.stringify(flow), name, description),
  deleteFlowTemplate: (filepath) => call('delete_flow_template', filepath),
  loadFlowTemplate: (filepath) => call('load_flow_template', filepath),
  clipboardWrite: (text) => call('clipboard_write', text),
  readLocalImage: (filepath) => call('read_local_image', filepath),
  pickTemplateImage: () => call('pick_template_image'),
  saveTemplateImage: (dataUrl, filename = null) => call('save_template_image', dataUrl, filename),
  exportText: (text, filename = null) => call('export_text', text, filename),
  getRunLogInfo: () => call('get_run_log_info'),
  exportRunLog: () => call('export_run_log'),
  windowMinimize: () => call('window_minimize'),
  windowToggleMaximize: () => call('window_toggle_maximize'),
  windowClose: () => call('window_close'),
  windowIsMaximized: () => call('window_is_maximized'),
  windowToggleOnTop: () => call('window_toggle_on_top'),
  windowIsOnTop: () => call('window_is_on_top'),
};
