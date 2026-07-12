/**
 * Nexuz Unity UI click capture/playback (IL2CPP uGUI MVP).
 * Persists stable identity (hierarchy path), never store raw ptr in FlowModel.
 */
'use strict';

var state = {
  hooked: false,
  recording: false,
  sequence: false,
  lastError: null,
  queue: [],
  // session ptr cache: key -> NativePointer
  ptrByKey: {},
};

function ok(extra) {
  var o = { ok: true };
  if (extra) {
    for (var k in extra) o[k] = extra[k];
  }
  return o;
}

function fail(msg, extra) {
  state.lastError = String(msg || 'error');
  var o = { ok: false, error: state.lastError, message: state.lastError };
  if (extra) {
    for (var k in extra) o[k] = extra[k];
  }
  return o;
}

function api(name, ret, args) {
  var addr = Module.findExportByName(null, name) || Module.findExportByName('GameAssembly.dll', name) || Module.findExportByName('libil2cpp.so', name);
  if (!addr) return null;
  return new NativeFunction(addr, ret, args);
}

var il2cpp_domain_get = api('il2cpp_domain_get', 'pointer', []);
var il2cpp_domain_get_assemblies = api('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
var il2cpp_assembly_get_image = api('il2cpp_assembly_get_image', 'pointer', ['pointer']);
var il2cpp_class_from_name = api('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
var il2cpp_class_get_method_from_name = api('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
var il2cpp_runtime_invoke = api('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var il2cpp_object_get_class = api('il2cpp_object_get_class', 'pointer', ['pointer']);
var il2cpp_class_get_name = api('il2cpp_class_get_name', 'pointer', ['pointer']);
var il2cpp_class_get_namespace = api('il2cpp_class_get_namespace', 'pointer', ['pointer']);
var il2cpp_string_new = api('il2cpp_string_new', 'pointer', ['pointer']);

function readCString(p) {
  try {
    return p && !p.isNull() ? p.readUtf8String() : '';
  } catch (e) {
    return '';
  }
}

function findMethodInfo(imageNs, className, methodName, argc) {
  if (!il2cpp_domain_get || !il2cpp_class_from_name || !il2cpp_class_get_method_from_name) return NULL;
  try {
    var domain = il2cpp_domain_get();
    var sizeBuf = Memory.alloc(Process.pointerSize);
    sizeBuf.writeU32(0);
    var assemblies = il2cpp_domain_get_assemblies(domain, sizeBuf);
    var count = sizeBuf.readU32();
    var ns = Memory.allocUtf8String(imageNs);
    var cn = Memory.allocUtf8String(className);
    for (var i = 0; i < count; i++) {
      var asm = assemblies.add(i * Process.pointerSize).readPointer();
      var image = il2cpp_assembly_get_image(asm);
      var klass = il2cpp_class_from_name(image, ns, cn);
      if (klass && !klass.isNull()) {
        var method = il2cpp_class_get_method_from_name(klass, Memory.allocUtf8String(methodName), argc);
        if (method && !method.isNull()) {
          return method; // MethodInfo*
        }
      }
    }
  } catch (e) {
    state.lastError = 'findMethodInfo: ' + e;
  }
  return NULL;
}

function methodNativePtr(imageNs, className, methodName, argc) {
  var info = findMethodInfo(imageNs, className, methodName, argc);
  if (!info || info.isNull()) return NULL;
  try {
    return info.readPointer(); // MethodInfo.methodPointer
  } catch (e) {
    return NULL;
  }
}

function classNameOf(obj) {
  try {
    if (!obj || obj.isNull() || !il2cpp_object_get_class) return '';
    var klass = il2cpp_object_get_class(obj);
    var ns = readCString(il2cpp_class_get_namespace(klass));
    var name = readCString(il2cpp_class_get_name(klass));
    return ns ? ns + '.' + name : name;
  } catch (e) {
    return '';
  }
}

// Optional Unity helpers — soft fail if missing
var get_transform = null;
var get_parent = null;
var get_name = null;
var get_sibling_index = null;
var get_child_count = null;
var get_child = null;
var execute_events_execute = null;

function initUnityHelpers() {
  get_transform = findMethodInfo('UnityEngine', 'Component', 'get_transform', 0);
  get_parent = findMethodInfo('UnityEngine', 'Transform', 'get_parent', 0);
  get_name = findMethodInfo('UnityEngine', 'Object', 'get_name', 0);
  get_sibling_index = findMethodInfo('UnityEngine', 'Transform', 'get_siblingIndex', 0);
  get_child_count = findMethodInfo('UnityEngine', 'Transform', 'get_childCount', 0);
  get_child = findMethodInfo('UnityEngine', 'Transform', 'GetChild', 1);
}

function invoke0(methodInfo, obj) {
  if (!methodInfo || methodInfo.isNull() || !il2cpp_runtime_invoke) return NULL;
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(NULL);
  return il2cpp_runtime_invoke(methodInfo, obj, NULL, exc);
}

function invoke1(methodInfo, obj, arg0) {
  if (!methodInfo || methodInfo.isNull() || !il2cpp_runtime_invoke) return NULL;
  var args = Memory.alloc(Process.pointerSize);
  args.writePointer(arg0);
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(NULL);
  return il2cpp_runtime_invoke(methodInfo, obj, args, exc);
}

function objectName(obj) {
  try {
    if (!get_name) return '';
    var s = invoke0(get_name, obj);
    if (!s || s.isNull()) return '';
    // Il2CppString: length at +0x10, chars at +0x14 (utf16) — approximate
    var len = s.add(0x10).readInt();
    if (len <= 0 || len > 256) return '';
    return s.add(0x14).readUtf16String(len);
  } catch (e) {
    return '';
  }
}

function buildHierarchy(component) {
  var parts = [];
  var siblingIndex = 0;
  try {
    if (!get_transform) {
      return { hierarchy_path: 'Unknown', sibling_index: 0, display_name: 'Unknown' };
    }
    var t = invoke0(get_transform, component);
    if (!t || t.isNull()) {
      return { hierarchy_path: 'Unknown', sibling_index: 0, display_name: 'Unknown' };
    }
    var guard = 0;
    while (t && !t.isNull() && guard < 64) {
      var n = objectName(t) || ('node' + guard);
      parts.unshift(n);
      if (!get_parent) break;
      t = invoke0(get_parent, t);
      guard++;
    }
  } catch (e) {
    state.lastError = 'buildHierarchy: ' + e;
  }
  var path = parts.join('/') || 'Unknown';
  return {
    hierarchy_path: path,
    sibling_index: siblingIndex,
    display_name: parts.length ? parts[parts.length - 1] : 'Unknown',
  };
}

function pointerButtonName(eventData) {
  // UnityEngine.EventSystems.PointerEventData.button : InputButton enum (0 left, 1 right, 2 middle)
  // Field offset varies; try common offsets then default left.
  try {
    if (!eventData || eventData.isNull()) return 'left';
    var candidates = [0x2c, 0x30, 0x34, 0x38, 0x40, 0x48];
    for (var i = 0; i < candidates.length; i++) {
      var v = eventData.add(candidates[i]).readInt();
      if (v === 0) return 'left';
      if (v === 1) return 'right';
      if (v === 2) return 'middle';
    }
  } catch (e) {}
  return 'left';
}

function stableKey(info) {
  return [info.hierarchy_path || '', info.component_type || '', String(info.sibling_index || 0)].join('|');
}

function captureFromClick(component, eventData) {
  var hier = buildHierarchy(component);
  var ctype = classNameOf(component) || 'UnityEngine.UI.Button';
  var button = pointerButtonName(eventData);
  var info = {
    hierarchy_path: hier.hierarchy_path,
    component_type: ctype,
    sibling_index: hier.sibling_index,
    display_name: hier.display_name,
    button: button,
  };
  var key = stableKey(info);
  try {
    state.ptrByKey[key] = component;
  } catch (e) {}
  return info;
}

function hookOnPointerClick(classNs, className) {
  var impl = methodNativePtr(classNs, className, 'OnPointerClick', 1);
  if (!impl || impl.isNull()) {
    return false;
  }
  Interceptor.attach(impl, {
    onEnter: function (args) {
      if (!state.recording) return;
      try {
        var self = args[0];
        var eventData = args[1];
        var info = captureFromClick(self, eventData);
        if (state.sequence) {
          state.queue.push(info);
        } else {
          state.queue = [info];
          state.recording = false;
        }
      } catch (e) {
        state.lastError = 'OnPointerClick hook: ' + e;
      }
    },
  });
  return true;
}

function attachHooks() {
  try {
    initUnityHelpers();
    var okAny = false;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Button') || okAny;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Toggle') || okAny;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Dropdown') || okAny;
    // TMP / newer dropdown
    okAny = hookOnPointerClick('TMPro', 'TMP_Dropdown') || okAny;
    state.hooked = okAny;
    if (!okAny) {
      return fail('未能 Hook OnPointerClick（确认目标为 Unity IL2CPP 且程序集可解析）');
    }
    return ok({ hooked: true });
  } catch (e) {
    return fail(String(e));
  }
}

function findByPath(hierarchyPath, componentType, siblingIndex) {
  // Prefer session cache
  var key = [hierarchyPath || '', componentType || '', String(siblingIndex || 0)].join('|');
  if (state.ptrByKey[key] && !state.ptrByKey[key].isNull()) {
    return state.ptrByKey[key];
  }
  // Walk from cached pointers matching path suffix
  for (var k in state.ptrByKey) {
    var p = state.ptrByKey[k];
    if (!p || p.isNull()) continue;
    try {
      var hier = buildHierarchy(p);
      if (hier.hierarchy_path === hierarchyPath) {
        return p;
      }
    } catch (e) {}
  }
  return NULL;
}

function resolve(stableId) {
  try {
    var path = stableId && stableId.hierarchy_path;
    var ctype = (stableId && stableId.component_type) || 'UnityEngine.UI.Button';
    var sib = (stableId && stableId.sibling_index) || 0;
    if (!path) return fail('hierarchy_path 为空');
    var p = findByPath(path, ctype, sib);
    if (!p || p.isNull()) {
      return fail('无法解析 UI 路径: ' + path);
    }
    return ok({ ptr: p.toString() });
  } catch (e) {
    return fail(String(e));
  }
}

function invokeClick(stableId, button) {
  try {
    var r = resolve(stableId);
    if (!r.ok) return r;
    var path = stableId.hierarchy_path;
    var ctype = stableId.component_type || 'UnityEngine.UI.Button';
    var sib = stableId.sibling_index || 0;
    var component = findByPath(path, ctype, sib);
    if (!component || component.isNull()) return fail('组件指针无效');

    var clickMethod = findMethodInfo('UnityEngine.UI', 'Button', 'Press', 0);
    if (clickMethod && !clickMethod.isNull()) {
      invoke0(clickMethod, component);
      return ok({ invoked: 'Press', button: button || 'left' });
    }
    var getOnClick = findMethodInfo('UnityEngine.UI', 'Button', 'get_onClick', 0);
    var unityEventInvoke = findMethodInfo('UnityEngine.Events', 'UnityEvent', 'Invoke', 0);
    if (getOnClick && unityEventInvoke && !getOnClick.isNull() && !unityEventInvoke.isNull()) {
      var ev = invoke0(getOnClick, component);
      if (ev && !ev.isNull()) {
        invoke0(unityEventInvoke, ev);
        return ok({ invoked: 'onClick.Invoke', button: button || 'left' });
      }
    }
    return fail('无法调用点击（Press/onClick 均不可用）');
  } catch (e) {
    return fail(String(e));
  }
}

rpc.exports = {
  attachhooks: function () {
    return JSON.stringify(attachHooks());
  },
  startsequencerecord: function () {
    state.sequence = true;
    state.recording = true;
    state.queue = [];
    return JSON.stringify(ok({ recording: true, sequence: true }));
  },
  stopsequencerecord: function () {
    state.recording = false;
    state.sequence = false;
    var q = state.queue.slice();
    state.queue = [];
    return JSON.stringify(ok({ items: q }));
  },
  setrecordtarget: function (active) {
    // single-shot: active truthy => record next click then auto stop
    state.sequence = false;
    state.recording = !!active;
    if (active) state.queue = [];
    return JSON.stringify(ok({ recording: state.recording, sequence: false }));
  },
  drainrecorded: function () {
    var q = state.queue.slice();
    state.queue = [];
    return JSON.stringify(ok({ items: q }));
  },
  resolve: function (stableId) {
    if (typeof stableId === 'string') {
      try { stableId = JSON.parse(stableId); } catch (e) {}
    }
    return JSON.stringify(resolve(stableId || {}));
  },
  invokeclick: function (stableId, button) {
    if (typeof stableId === 'string') {
      try { stableId = JSON.parse(stableId); } catch (e) {}
    }
    return JSON.stringify(invokeClick(stableId || {}, button || 'left'));
  },
  status: function () {
    return JSON.stringify({
      hooked: state.hooked,
      recording: state.recording,
      sequence: state.sequence,
      queueLength: state.queue.length,
      lastError: state.lastError,
    });
  },
};
