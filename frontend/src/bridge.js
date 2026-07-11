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
      { name: 'x', type: 'number', label: 'X', default: 0 },
      { name: 'y', type: 'number', label: 'Y', default: 0 },
      { name: 'button', type: 'select', label: '按键', options: ['left', 'right', 'middle'], default: 'left' },
      { name: 'click_type', type: 'select', label: '点击类型', options: ['single', 'double'], default: 'single' },
      { name: 'move_duration', type: 'number', label: '移动耗时(ms)', default: 0 },
    ],
    outputs: [],
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
    inputs: [{ name: 'keys', type: 'keys', label: '按键(组合)', default: ['enter'] }],
    outputs: [],
  },
  {
    type: 'type_text',
    label: '输入文本',
    category: '动作类',
    inputs: [
      { name: 'text', type: 'string', label: '文本', default: '' },
      { name: 'interval', type: 'number', label: '字符间隔(ms)', default: 0 },
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
      { name: 'duration', type: 'number', label: '耗时(ms)', default: 300 },
    ],
    outputs: [],
  },
  {
    type: 'color_detect',
    label: '区域取色',
    category: '识别类',
    inputs: [
      { name: 'x', type: 'number', label: 'X（单点）', default: 0 },
      { name: 'y', type: 'number', label: 'Y（单点）', default: 0 },
      { name: 'region', type: 'rect', label: '区域(可选)', default: null },
    ],
    outputs: [{ name: 'color', type: 'string' }],
  },
  {
    type: 'if_color_match',
    label: '颜色匹配',
    category: '识别类',
    inputs: [
      { name: 'x', type: 'number', label: 'X', default: 0 },
      { name: 'y', type: 'number', label: 'Y', default: 0 },
      { name: 'region', type: 'rect', label: '区域(可选)', default: null },
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
    inputs: [{ name: 'expression', type: 'string', label: '表达式', default: '' }],
    outputs: [{ name: 'matched', type: 'boolean' }],
  },
  {
    type: 'switch',
    label: '多分支',
    category: '控制类',
    inputs: [
      { name: 'variable', type: 'string', label: '变量引用', default: '' },
      { name: 'cases', type: 'cases', label: '分支', default: [] },
      { name: 'default', type: 'string', label: '默认节点ID', default: '' },
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
    type: 'loop_while',
    label: '条件循环',
    category: '控制类',
    inputs: [
      { name: 'expression', type: 'string', label: '继续条件', default: '' },
      { name: 'max_times', type: 'number', label: '最大次数', default: 10000 },
    ],
    outputs: [{ name: 'matched', type: 'boolean' }],
  },
  {
    type: 'loop_forever',
    label: '无限循环',
    category: '控制类',
    inputs: [
      { name: 'exit_condition', type: 'string', label: '退出条件(可选)', default: '' },
      { name: 'check_interval_ms', type: 'number', label: '每轮间隔(ms)', default: 200 },
      { name: 'max_times', type: 'number', label: '安全最大次数', default: 1000000 },
    ],
    outputs: [],
  },
  {
    type: 'ocr_recognize',
    label: 'OCR 文字识别',
    category: '识别类',
    inputs: [
      { name: 'region', type: 'rect', label: '识别区域（推荐：拖拽框选）', default: null },
      { name: 'x', type: 'number', label: '起点X（无区域时用）', default: 0 },
      { name: 'y', type: 'number', label: '起点Y（无区域时用）', default: 0 },
      { name: 'width', type: 'number', label: '宽度（无区域时用）', default: 320 },
      { name: 'height', type: 'number', label: '高度（无区域时用）', default: 80 },
      { name: 'anchor_template', type: 'string', label: '锚点模板路径(可选，先找图再识别)', default: '' },
      { name: 'anchor_threshold', type: 'number', label: '锚点相似度阈值', default: 0.8 },
      { name: 'anchor_offset_x', type: 'number', label: '相对锚点左上角偏移X', default: 0 },
      { name: 'anchor_offset_y', type: 'number', label: '相对锚点左上角偏移Y', default: 0 },
      { name: 'anchor_ocr_width', type: 'number', label: '锚点模式下识别宽度(0=用模板宽)', default: 0 },
      { name: 'anchor_ocr_height', type: 'number', label: '锚点模式下识别高度(0=用模板高)', default: 0 },
      { name: 'lang', type: 'select', label: '语言', options: ['auto', 'ch', 'en'], default: 'auto' },
      { name: 'min_confidence', type: 'number', label: '最低置信度(0-1)', default: 0.3 },
    ],
    outputs: [
      { name: 'text', type: 'string' },
      { name: 'confidence', type: 'number' },
      { name: 'boxes', type: 'any' },
      { name: 'region', type: 'any' },
      { name: 'anchor', type: 'any' },
    ],
  },
  {
    type: 'if_text_contains',
    label: '文字匹配',
    category: '识别类',
    inputs: [
      { name: 'region', type: 'rect', label: '识别区域（推荐：拖拽框选）', default: null },
      { name: 'x', type: 'number', label: '起点X（无区域时用）', default: 0 },
      { name: 'y', type: 'number', label: '起点Y（无区域时用）', default: 0 },
      { name: 'width', type: 'number', label: '宽度（无区域时用）', default: 320 },
      { name: 'height', type: 'number', label: '高度（无区域时用）', default: 80 },
      { name: 'anchor_template', type: 'string', label: '锚点模板路径(可选，先找图再识别)', default: '' },
      { name: 'anchor_threshold', type: 'number', label: '锚点相似度阈值', default: 0.8 },
      { name: 'anchor_offset_x', type: 'number', label: '相对锚点左上角偏移X', default: 0 },
      { name: 'anchor_offset_y', type: 'number', label: '相对锚点左上角偏移Y', default: 0 },
      { name: 'anchor_ocr_width', type: 'number', label: '锚点模式下识别宽度(0=用模板宽)', default: 0 },
      { name: 'anchor_ocr_height', type: 'number', label: '锚点模式下识别高度(0=用模板高)', default: 0 },
      { name: 'expect_text', type: 'string', label: '期望文字', default: '' },
      {
        name: 'match_mode',
        type: 'select',
        label: '匹配模式',
        options: ['contains', 'exact', 'regex'],
        default: 'contains',
      },
      { name: 'lang', type: 'select', label: '语言', options: ['auto', 'ch', 'en'], default: 'auto' },
      { name: 'min_confidence', type: 'number', label: '最低置信度(0-1)', default: 0.3 },
    ],
    outputs: [
      { name: 'matched', type: 'boolean' },
      { name: 'actual_text', type: 'string' },
    ],
  },
  {
    type: 'find_image',
    label: '图像模板匹配',
    category: '识别类',
    inputs: [
      { name: 'template_image', type: 'string', label: '模板图片路径', default: '' },
      { name: 'search_region', type: 'rect', label: '搜索区域(可选)', default: null },
      { name: 'threshold', type: 'number', label: '相似度阈值(0-1)', default: 0.8 },
    ],
    outputs: [
      { name: 'found', type: 'boolean' },
      { name: 'x', type: 'number' },
      { name: 'y', type: 'number' },
      { name: 'score', type: 'number' },
    ],
  },
  {
    type: 'screenshot',
    label: '区域截图',
    category: '识别类',
    inputs: [
      { name: 'region', type: 'rect', label: '截图区域', default: null },
      { name: 'save_path', type: 'string', label: '保存路径(可选，空则自动)', default: '' },
    ],
    outputs: [
      { name: 'path', type: 'string' },
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
      },
      { name: 'region', type: 'rect', label: '检测区域(颜色/文字)', default: null },
      { name: 'x', type: 'number', label: '单点X(颜色可选)', default: 0 },
      { name: 'y', type: 'number', label: '单点Y(颜色可选)', default: 0 },
      { name: 'target_color', type: 'color', label: '目标颜色', default: '#FF0000' },
      { name: 'tolerance', type: 'number', label: '颜色容差', default: 20 },
      { name: 'expect_text', type: 'string', label: '期望文字(包含)', default: '' },
      { name: 'expression', type: 'string', label: '表达式(为真则继续)', default: '' },
      { name: 'timeout_ms', type: 'number', label: '超时毫秒(0=不限)', default: 30000 },
      { name: 'poll_interval_ms', type: 'number', label: '轮询间隔毫秒', default: 300 },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'elapsed_ms', type: 'number' },
      { name: 'detail', type: 'string' },
    ],
  },
  {
    type: 'schedule_trigger',
    label: '定时触发',
    category: '控制类',
    inputs: [
      {
        name: 'trigger_type',
        type: 'select',
        label: '触发类型',
        options: ['interval', 'once', 'cron'],
        default: 'interval',
      },
      { name: 'interval_seconds', type: 'number', label: '周期秒数(interval)', default: 60 },
      { name: 'run_at', type: 'string', label: '单次时间(once)', default: '' },
      { name: 'cron_expression', type: 'string', label: 'Cron(分 时 日 月 周)', default: '0 * * * *' },
      { name: 'enabled', type: 'select', label: '启用', options: ['true', 'false'], default: 'true' },
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
      { name: 'subflow_path', type: 'string', label: '子流程 .flow.json 路径', default: '' },
      {
        name: 'inherit_variables',
        type: 'select',
        label: '继承父流程变量',
        options: ['true', 'false'],
        default: 'true',
      },
    ],
    outputs: [
      { name: 'ok', type: 'boolean' },
      { name: 'context_keys', type: 'number' },
    ],
  },
];

async function call(method, ...args) {
  const api = getApi();
  if (!api || typeof api[method] !== 'function') {
    return mockCall(method, ...args);
  }
  return api[method](...args);
}

function mockCall(method, ...args) {
  switch (method) {
    case 'ping':
      return Promise.resolve({ ok: true, message: 'pong (browser mock)', dpi_scale: 1 });
    case 'get_block_registry':
      return Promise.resolve(MOCK_SCHEMAS);
    case 'run_flow':
      return Promise.resolve({ ok: false, error: '请在桌面客户端中运行流程（python backend/main.py --dev）' });
    case 'save_flow':
    case 'load_flow':
    case 'start_recording':
    case 'stop_recording':
    case 'pick_point':
    case 'pick_region':
    case 'capture_template':
    case 'pause_flow':
    case 'resume_flow':
    case 'stop_flow':
    case 'step_flow':
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
  getBlockRegistry: () => call('get_block_registry'),
  getScreenInfo: () => call('get_screen_info'),
  runFlow: (flow, stepMode = false) => call('run_flow', JSON.stringify(flow), stepMode),
  pauseFlow: () => call('pause_flow'),
  resumeFlow: () => call('resume_flow'),
  stopFlow: () => call('stop_flow'),
  stepFlow: () => call('step_flow'),
  isRunning: () => call('is_running'),
  saveFlow: (flow, filepath = null) => call('save_flow', JSON.stringify(flow), filepath),
  loadFlow: (filepath = null) => call('load_flow', filepath),
  validateFlow: (flow) => call('validate_flow', JSON.stringify(flow)),
  startRecording: (minIntervalMs = 50, hideWindow = true) =>
    call('start_recording', minIntervalMs, hideWindow),
  stopRecording: () => call('stop_recording'),
  pickPoint: (hideWindow = true) => call('pick_point', hideWindow),
  pickRegion: (hideWindow = true) => call('pick_region', hideWindow),
  captureTemplate: (hideWindow = true, filename = null) =>
    call('capture_template', hideWindow, filename),
  listScheduleJobs: () => call('list_schedule_jobs'),
  removeScheduleJob: (jobId) => call('remove_schedule_job', jobId),
};
