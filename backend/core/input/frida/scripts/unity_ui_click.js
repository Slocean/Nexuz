/**
 * Nexuz Unity UI click capture/playback (IL2CPP uGUI MVP).
 * Persists stable identity (hierarchy path), never store raw ptr in FlowModel.
 *
 * IL2CPP exports are resolved lazily inside attachHooks (GameAssembly may not
 * be ready at script load time).
 */
'use strict';

var state = {
  hooked: false,
  recording: false,
  sequence: false,
  lastError: null,
  queue: [],
  ptrByKey: {},
  il2cppReady: false,
  // TBH-style: never call Button.Press from Frida RPC thread — queue for EventSystem.Update
  pressJobs: [],
  resolveJobs: [],
  mainThreadHooked: false,
};

var il2cpp = {
  domain_get: null,
  domain_get_assemblies: null,
  assembly_get_image: null,
  class_from_name: null,
  class_get_method_from_name: null,
  runtime_invoke: null,
  object_get_class: null,
  class_get_name: null,
  class_get_namespace: null,
  class_get_type: null,
  type_get_object: null,
};

var get_transform = null;
var get_parent = null;
var get_name = null;
var get_sibling_index = null;
var get_child_count = null;
var get_child = null;

function ok(extra) {
  var o = { ok: true };
  if (extra) for (var k in extra) o[k] = extra[k];
  return o;
}

function fail(msg, extra) {
  state.lastError = String(msg || 'error');
  var o = { ok: false, error: state.lastError, message: state.lastError };
  if (extra) for (var k in extra) o[k] = extra[k];
  return o;
}

function findGameAssemblyModule() {
  try {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
      var n = (mods[i].name || '').toLowerCase();
      if (n.indexOf('gameassembly') !== -1) return mods[i];
    }
  } catch (e) {}
  return null;
}

function findExport(name) {
  // Prefer jade-style: module.getExportByName after locating GameAssembly
  var ga = findGameAssemblyModule();
  if (ga) {
    try {
      var addr = ga.getExportByName(name);
      if (addr && !addr.isNull()) return addr;
    } catch (e) {}
    try {
      var addr2 = Module.findExportByName(ga.name, name);
      if (addr2 && !addr2.isNull()) return addr2;
    } catch (e2) {}
  }
  var modNames = [null, 'GameAssembly.dll', 'GameAssembly', 'UnityPlayer.dll', 'libil2cpp.so'];
  for (var i = 0; i < modNames.length; i++) {
    try {
      var a = Module.findExportByName(modNames[i], name);
      if (a && !a.isNull()) return a;
    } catch (e3) {}
  }
  return null;
}

function waitForGameAssembly(timeoutMs) {
  var deadline = Date.now() + (timeoutMs || 8000);
  while (Date.now() < deadline) {
    var ga = findGameAssemblyModule();
    if (ga) return ga;
    Thread.sleep(0.25);
  }
  return findGameAssemblyModule();
}

function listModuleHint() {
  try {
    var mods = Process.enumerateModules();
    var names = [];
    for (var i = 0; i < Math.min(mods.length, 40); i++) {
      names.push(mods[i].name);
    }
    return names.join(', ');
  } catch (e) {
    return '';
  }
}

function bindIl2Cpp() {
  var ga = waitForGameAssembly(8000);
  if (!ga) {
    state.lastError =
      '未找到 GameAssembly.dll（已等待加载）。模块抽样: ' + listModuleHint();
    state.il2cppReady = false;
    return false;
  }
  function nf(name, ret, args) {
    var addr = null;
    try {
      addr = ga.getExportByName(name);
    } catch (e) {}
    if (!addr || addr.isNull()) addr = findExport(name);
    if (!addr || addr.isNull()) return null;
    try {
      return new NativeFunction(addr, ret, args);
    } catch (e2) {
      return null;
    }
  }
  il2cpp.domain_get = nf('il2cpp_domain_get', 'pointer', []);
  il2cpp.domain_get_assemblies = nf('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
  il2cpp.assembly_get_image = nf('il2cpp_assembly_get_image', 'pointer', ['pointer']);
  il2cpp.class_from_name = nf('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
  il2cpp.class_get_method_from_name = nf('il2cpp_class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
  il2cpp.runtime_invoke = nf('il2cpp_runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
  il2cpp.object_get_class = nf('il2cpp_object_get_class', 'pointer', ['pointer']);
  il2cpp.class_get_name = nf('il2cpp_class_get_name', 'pointer', ['pointer']);
  il2cpp.class_get_namespace = nf('il2cpp_class_get_namespace', 'pointer', ['pointer']);
  il2cpp.class_get_type = nf('il2cpp_class_get_type', 'pointer', ['pointer']);
  il2cpp.type_get_object = nf('il2cpp_type_get_object', 'pointer', ['pointer']);
  // Hooks need method lookup; playback uses NativeFunction(Press) and may not need runtime_invoke
  state.il2cppReady = !!(
    il2cpp.domain_get &&
    il2cpp.class_from_name &&
    il2cpp.class_get_method_from_name
  );
  if (!state.il2cppReady) {
    var missing = [];
    if (!il2cpp.domain_get) missing.push('il2cpp_domain_get');
    if (!il2cpp.class_from_name) missing.push('il2cpp_class_from_name');
    if (!il2cpp.class_get_method_from_name) missing.push('il2cpp_class_get_method_from_name');
    if (!il2cpp.runtime_invoke) missing.push('il2cpp_runtime_invoke');
    state.lastError =
      '已找到 ' + ga.name + ' 但缺少导出: ' + missing.join(', ');
  }
  return state.il2cppReady;
}

function readCString(p) {
  try {
    return p && !p.isNull() ? p.readUtf8String() : '';
  } catch (e) {
    return '';
  }
}

function findMethodInfo(imageNs, className, methodName, argc) {
  if (!state.il2cppReady && !bindIl2Cpp()) return NULL;
  if (!il2cpp.domain_get || !il2cpp.class_from_name || !il2cpp.class_get_method_from_name) return NULL;
  try {
    var domain = il2cpp.domain_get();
    var sizeBuf = Memory.alloc(Process.pointerSize);
    sizeBuf.writeU32(0);
    var assemblies = il2cpp.domain_get_assemblies(domain, sizeBuf);
    var count = sizeBuf.readU32();
    var ns = Memory.allocUtf8String(imageNs);
    var cn = Memory.allocUtf8String(className);
    for (var i = 0; i < count; i++) {
      var asm = assemblies.add(i * Process.pointerSize).readPointer();
      var image = il2cpp.assembly_get_image(asm);
      var klass = il2cpp.class_from_name(image, ns, cn);
      if (klass && !klass.isNull()) {
        var method = il2cpp.class_get_method_from_name(
          klass,
          Memory.allocUtf8String(methodName),
          argc
        );
        if (method && !method.isNull()) return method;
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
    var p = info.readPointer();
    if (!p || p.isNull()) return NULL;
    return p;
  } catch (e) {
    return NULL;
  }
}

function isReadable(p) {
  try {
    if (!p || p.isNull()) return false;
    var r = Process.findRangeByAddress(p);
    return !!(r && r.protection && r.protection.indexOf('r') !== -1);
  } catch (e) {
    return false;
  }
}

function isAliveObject(p) {
  try {
    if (!isReadable(p)) return false;
    if (il2cpp.object_get_class) {
      var klass = il2cpp.object_get_class(p);
      return !!(klass && !klass.isNull());
    }
    p.readU8();
    return true;
  } catch (e) {
    return false;
  }
}

function methodPointerOrNull(methodInfo) {
  try {
    if (!methodInfo || methodInfo.isNull()) return NULL;
    var mp = methodInfo.readPointer();
    if (!mp || mp.isNull()) return NULL;
    return mp;
  } catch (e) {
    return NULL;
  }
}

function invoke0(methodInfo, obj) {
  if (!methodInfo || methodInfo.isNull()) {
    throw new Error('MethodInfo 为空，无法 invoke');
  }
  if (!il2cpp.runtime_invoke) {
    throw new Error('il2cpp_runtime_invoke 未绑定（无法回放点击）');
  }
  if (!methodPointerOrNull(methodInfo)) {
    throw new Error('方法指针为 0，无法 invoke（MethodInfo.methodPointer=null）');
  }
  if (obj && !isAliveObject(obj)) {
    throw new Error('目标组件指针已失效（可能界面已销毁，请重新录入）');
  }
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(NULL);
  var ret = il2cpp.runtime_invoke(methodInfo, obj || NULL, NULL, exc);
  var ex = exc.readPointer();
  if (ex && !ex.isNull()) {
    throw new Error('il2cpp_runtime_invoke 抛出托管异常');
  }
  return ret;
}

function invoke1ptr(methodInfo, obj, arg0) {
  if (!methodInfo || methodInfo.isNull()) {
    throw new Error('MethodInfo 为空，无法 invoke');
  }
  if (!il2cpp.runtime_invoke) {
    throw new Error('il2cpp_runtime_invoke 未绑定');
  }
  var args = Memory.alloc(Process.pointerSize);
  args.writePointer(arg0 || NULL);
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(NULL);
  var ret = il2cpp.runtime_invoke(methodInfo, obj || NULL, args, exc);
  var ex = exc.readPointer();
  if (ex && !ex.isNull()) {
    throw new Error('il2cpp_runtime_invoke 抛出托管异常');
  }
  return ret;
}

function findClass(imageNs, className) {
  if (!state.il2cppReady && !bindIl2Cpp()) return NULL;
  if (!il2cpp.domain_get || !il2cpp.class_from_name) return NULL;
  try {
    var domain = il2cpp.domain_get();
    var sizeBuf = Memory.alloc(Process.pointerSize);
    sizeBuf.writeU32(0);
    var assemblies = il2cpp.domain_get_assemblies(domain, sizeBuf);
    var count = sizeBuf.readU32();
    var ns = Memory.allocUtf8String(imageNs);
    var cn = Memory.allocUtf8String(className);
    for (var i = 0; i < count; i++) {
      var asm = assemblies.add(i * Process.pointerSize).readPointer();
      var image = il2cpp.assembly_get_image(asm);
      var klass = il2cpp.class_from_name(image, ns, cn);
      if (klass && !klass.isNull()) return klass;
    }
  } catch (e) {
    state.lastError = 'findClass: ' + e;
  }
  return NULL;
}

function typeObjectOfClass(klass) {
  if (!klass || klass.isNull()) return NULL;
  if (!il2cpp.class_get_type || !il2cpp.type_get_object) {
    // Rebind exports if attach happened before these were wired
    try {
      bindIl2Cpp();
    } catch (e0) {}
  }
  if (!il2cpp.class_get_type || !il2cpp.type_get_object) return NULL;
  try {
    var t = il2cpp.class_get_type(klass);
    if (!t || t.isNull()) return NULL;
    var obj = il2cpp.type_get_object(t);
    if (!obj || obj.isNull()) return NULL;
    return obj;
  } catch (e) {
    return NULL;
  }
}

function parseComponentType(componentType) {
  var raw = String(componentType || 'UnityEngine.UI.Button');
  var lastDot = raw.lastIndexOf('.');
  if (lastDot <= 0) return { ns: 'UnityEngine.UI', name: raw || 'Button' };
  return { ns: raw.slice(0, lastDot), name: raw.slice(lastDot + 1) };
}

/** Read Il2CppArray<Object> length/items (common 64-bit layout). */
function il2cppArrayLength(arr) {
  try {
    if (!arr || arr.isNull()) return 0;
    return arr.add(0x18).readS32();
  } catch (e) {
    return 0;
  }
}

function il2cppArrayGet(arr, index) {
  try {
    if (!arr || arr.isNull()) return NULL;
    return arr.add(0x20 + index * Process.pointerSize).readPointer();
  } catch (e) {
    return NULL;
  }
}

function findObjectsOfTypeAll(klass) {
  var typeObj = typeObjectOfClass(klass);
  if (!typeObj) return [];
  var method =
    findMethodInfo('UnityEngine', 'Resources', 'FindObjectsOfTypeAll', 1) ||
    findMethodInfo('UnityEngine', 'Object', 'FindObjectsOfType', 1);
  if (!method || method.isNull()) {
    state.lastError = '未找到 FindObjectsOfTypeAll / FindObjectsOfType';
    return [];
  }
  var arr = invoke1ptr(method, NULL, typeObj);
  var n = il2cppArrayLength(arr);
  var out = [];
  var max = Math.min(n, 512);
  for (var i = 0; i < max; i++) {
    var p = il2cppArrayGet(arr, i);
    if (p && !p.isNull() && isAliveObject(p)) out.push(p);
  }
  return out;
}

function invoke1(methodInfo, obj, arg0) {
  if (!methodInfo || methodInfo.isNull()) {
    throw new Error('MethodInfo 为空，无法 invoke');
  }
  if (!il2cpp.runtime_invoke) {
    throw new Error('il2cpp_runtime_invoke 未绑定');
  }
  if (!methodPointerOrNull(methodInfo)) {
    throw new Error('方法指针为 0，无法 invoke');
  }
  var args = Memory.alloc(Process.pointerSize);
  args.writePointer(arg0 || NULL);
  var exc = Memory.alloc(Process.pointerSize);
  exc.writePointer(NULL);
  var ret = il2cpp.runtime_invoke(methodInfo, obj || NULL, args, exc);
  var ex = exc.readPointer();
  if (ex && !ex.isNull()) {
    throw new Error('il2cpp_runtime_invoke 抛出托管异常');
  }
  return ret;
}

function findClass(imageNs, className) {
  if (!state.il2cppReady && !bindIl2Cpp()) return NULL;
  if (!il2cpp.domain_get || !il2cpp.class_from_name) return NULL;
  try {
    var domain = il2cpp.domain_get();
    var sizeBuf = Memory.alloc(Process.pointerSize);
    sizeBuf.writeU32(0);
    var assemblies = il2cpp.domain_get_assemblies(domain, sizeBuf);
    var count = sizeBuf.readU32();
    var ns = Memory.allocUtf8String(imageNs);
    var cn = Memory.allocUtf8String(className);
    for (var i = 0; i < count; i++) {
      var asm = assemblies.add(i * Process.pointerSize).readPointer();
      var image = il2cpp.assembly_get_image(asm);
      var klass = il2cpp.class_from_name(image, ns, cn);
      if (klass && !klass.isNull()) return klass;
    }
  } catch (e) {
    state.lastError = 'findClass: ' + e;
  }
  return NULL;
}

function typeObjectOfClass(klass) {
  if (!klass || klass.isNull()) return NULL;
  if (!il2cpp.class_get_type || !il2cpp.type_get_object) return NULL;
  try {
    var t = il2cpp.class_get_type(klass);
    if (!t || t.isNull()) return NULL;
    var obj = il2cpp.type_get_object(t);
    if (!obj || obj.isNull()) return NULL;
    return obj;
  } catch (e) {
    return NULL;
  }
}

function parseTypeName(full) {
  var s = String(full || '');
  var dot = s.lastIndexOf('.');
  if (dot < 0) return { ns: '', name: s };
  return { ns: s.slice(0, dot), name: s.slice(dot + 1) };
}

/** Read Il2CppArray length / element (common 64-bit layout). */
function il2cppArrayLength(arr) {
  if (!arr || arr.isNull()) return 0;
  try {
    return arr.add(0x18).readInt();
  } catch (e) {
    return 0;
  }
}

function il2cppArrayGet(arr, index) {
  if (!arr || arr.isNull()) return NULL;
  try {
    return arr.add(0x20 + index * Process.pointerSize).readPointer();
  } catch (e) {
    return NULL;
  }
}

/**
 * Find all instances of a UnityEngine.Object subclass via Resources.FindObjectsOfTypeAll.
 * Must run on Unity main thread.
 */
function findObjectsOfTypeAll(fullTypeName) {
  var parsed = parseTypeName(fullTypeName);
  var klass = findClass(parsed.ns, parsed.name);
  if (!klass || klass.isNull()) return [];
  var typeObj = typeObjectOfClass(klass);
  if (!typeObj || typeObj.isNull()) return [];
  var method =
    findMethodInfo('UnityEngine', 'Resources', 'FindObjectsOfTypeAll', 1) ||
    findMethodInfo('UnityEngine', 'Object', 'FindObjectsOfType', 1);
  if (!method || method.isNull()) return [];
  var arr = null;
  try {
    arr = invoke1(method, NULL, typeObj);
  } catch (e) {
    state.lastError = 'FindObjectsOfTypeAll: ' + e;
    return [];
  }
  var n = il2cppArrayLength(arr);
  var out = [];
  for (var i = 0; i < n && i < 4000; i++) {
    var p = il2cppArrayGet(arr, i);
    if (p && !p.isNull() && isAliveObject(p)) out.push(p);
  }
  return out;
}

/** Candidate UI component types to scan when resolving a hierarchy path. */
function resolveCandidateTypes(componentType) {
  var preferred = String(componentType || '').trim();
  var list = [];
  if (preferred) list.push(preferred);
  var fallbacks = [
    'UnityEngine.UI.Button',
    'UnityEngine.UI.Toggle',
    'UnityEngine.UI.Dropdown',
    'TMPro.TMP_Dropdown',
    'UnityEngine.UI.Selectable',
  ];
  for (var i = 0; i < fallbacks.length; i++) {
    if (list.indexOf(fallbacks[i]) < 0) list.push(fallbacks[i]);
  }
  return list;
}

/**
 * Live scene search by hierarchy_path. Main-thread only.
 * Returns NativePointer or NULL.
 */
function findByPathLive(hierarchyPath, componentType, siblingIndex) {
  var path = String(hierarchyPath || '');
  if (!path || path === 'Unknown') return NULL;
  var types = resolveCandidateTypes(componentType);
  var wantSibling = siblingIndex == null ? null : Number(siblingIndex);
  var fallback = NULL;
  for (var t = 0; t < types.length; t++) {
    var objs = findObjectsOfTypeAll(types[t]);
    for (var i = 0; i < objs.length; i++) {
      var comp = objs[i];
      try {
        var hier = buildHierarchy(comp);
        if (!hier || hier.hierarchy_path !== path) continue;
        if (wantSibling != null && Number(hier.sibling_index) === wantSibling) {
          return comp;
        }
        if (!fallback) fallback = comp;
        if (wantSibling == null) return comp;
      } catch (eWalk) {}
    }
  }
  return fallback || NULL;
}

function classNameOf(obj) {
  try {
    if (!obj || obj.isNull() || !il2cpp.object_get_class) return '';
    var klass = il2cpp.object_get_class(obj);
    var ns = readCString(il2cpp.class_get_namespace(klass));
    var name = readCString(il2cpp.class_get_name(klass));
    return ns ? ns + '.' + name : name;
  } catch (e) {
    return '';
  }
}

function initUnityHelpers() {
  get_transform = findMethodInfo('UnityEngine', 'Component', 'get_transform', 0);
  get_parent = findMethodInfo('UnityEngine', 'Transform', 'get_parent', 0);
  get_name = findMethodInfo('UnityEngine', 'Object', 'get_name', 0);
  get_sibling_index = findMethodInfo('UnityEngine', 'Transform', 'get_siblingIndex', 0);
  get_child_count = findMethodInfo('UnityEngine', 'Transform', 'get_childCount', 0);
  get_child = findMethodInfo('UnityEngine', 'Transform', 'GetChild', 1);
}

function objectName(obj) {
  try {
    if (!obj || obj.isNull()) return '';
    var s = null;
    if (replay.getName) {
      try {
        if (replay.getNameInfo) s = replay.getName(obj, replay.getNameInfo);
        else s = replay.getName(obj);
      } catch (e0) {
        s = null;
      }
    }
    if ((!s || s.isNull()) && get_name) {
      try {
        s = invoke0(get_name, obj);
      } catch (e1) {
        s = null;
      }
    }
    if (!s || s.isNull()) return '';
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
    var t = null;
    if (replay.getTransform) {
      try {
        if (replay.getTransformInfo) t = replay.getTransform(component, replay.getTransformInfo);
        else t = replay.getTransform(component);
      } catch (e0) {
        t = null;
      }
    }
    if ((!t || t.isNull()) && get_transform) {
      try {
        t = invoke0(get_transform, component);
      } catch (e1) {
        t = null;
      }
    }
    if (!t || t.isNull()) {
      return { hierarchy_path: 'Unknown', sibling_index: 0, display_name: 'Unknown' };
    }
    var guard = 0;
    while (t && !t.isNull() && guard < 64) {
      var n = objectName(t) || ('node' + guard);
      parts.unshift(n);
      var parent = null;
      if (replay.getParent) {
        try {
          if (replay.getParentInfo) parent = replay.getParent(t, replay.getParentInfo);
          else parent = replay.getParent(t);
        } catch (e2) {
          parent = null;
        }
      }
      if ((!parent || parent.isNull()) && get_parent) {
        try {
          parent = invoke0(get_parent, t);
        } catch (e3) {
          parent = null;
        }
      }
      if (!parent || parent.isNull()) break;
      t = parent;
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
  // UnityEngine.EventSystems.PointerEventData.InputButton: Left=0, Right=1, Middle=2
  // 先前一遇到 0 就返回 left，会把结构体里其它零字段误判为左键，导致右键录成 left。
  try {
    if (!eventData || eventData.isNull()) return 'left';
    var candidates = [0x2c, 0x30, 0x34, 0x38, 0x40, 0x48, 0x4c, 0x50];
    var sawLeft = false;
    for (var i = 0; i < candidates.length; i++) {
      var v = eventData.add(candidates[i]).readInt();
      if (v === 1) return 'right';
      if (v === 2) return 'middle';
      if (v === 0) sawLeft = true;
    }
    if (sawLeft) return 'left';
  } catch (e) {}
  return 'left';
}

function stableKey(info) {
  return [info.hierarchy_path || '', info.component_type || '', String(info.sibling_index || 0)].join('|');
}

var replay = {
  buttonPress: null,
  buttonPressInfo: null,
  buttonPressPtr: null,
  buttonOnPointerClick: null,
  buttonOnPointerClickInfo: null,
  lastPointerEvent: null,
  getName: null,
  getNameInfo: null,
  getTransform: null,
  getTransformInfo: null,
  getParent: null,
  getParentInfo: null,
  eventSystemUpdatePtr: null,
};

function captureFromClick(component, eventData, kind) {
  if (eventData && !eventData.isNull()) {
    try {
      replay.lastPointerEvent = eventData;
    } catch (e0) {}
  }
  var hier = buildHierarchy(component);
  var ctype = classNameOf(component) || 'UnityEngine.UI.Button';
  var button = pointerButtonName(eventData);
  var info = {
    hierarchy_path: hier.hierarchy_path,
    component_type: ctype,
    sibling_index: hier.sibling_index,
    display_name: hier.display_name,
    button: button,
    kind: kind || 'button',
  };
  try {
    state.ptrByKey[stableKey(info)] = component;
  } catch (e) {}
  return info;
}

function hookOnPointerClick(classNs, className, kind) {
  var info = findMethodInfo(classNs, className, 'OnPointerClick', 1);
  var impl = methodPointerOrNull(info);
  if (!impl) return false;
  Interceptor.attach(impl, {
    onEnter: function (args) {
      try {
        if (args[1] && !args[1].isNull()) replay.lastPointerEvent = args[1];
      } catch (e0) {}
      if (!state.recording) return;
      try {
        var row = captureFromClick(args[0], args[1], kind || 'button');
        if (state.sequence) state.queue.push(row);
        else {
          state.queue = [row];
          state.recording = false;
        }
      } catch (e) {
        state.lastError = 'OnPointerClick hook: ' + e;
      }
    },
  });
  return true;
}

function setupReplayNatives() {
  // Proven TBH approach: call native methodPointer(this, MethodInfo*) directly
  var pressInfo = findMethodInfo('UnityEngine.UI', 'Button', 'Press', 0);
  var pressPtr = methodPointerOrNull(pressInfo);
  if (pressPtr) {
    replay.buttonPressPtr = pressPtr;
    replay.buttonPress = new NativeFunction(pressPtr, 'void', ['pointer', 'pointer']);
    replay.buttonPressInfo = pressInfo;
    try {
      Interceptor.attach(pressPtr, {
        onEnter: function (args) {
          try {
            if (args[1] && !args[1].isNull()) replay.buttonPressInfo = args[1];
          } catch (e0) {}
        },
      });
    } catch (eHookPress) {}
  }
  var opcInfo = findMethodInfo('UnityEngine.UI', 'Button', 'OnPointerClick', 1);
  var opcPtr = methodPointerOrNull(opcInfo);
  if (opcPtr) {
    replay.buttonOnPointerClick = new NativeFunction(opcPtr, 'void', ['pointer', 'pointer', 'pointer']);
    replay.buttonOnPointerClickInfo = opcInfo;
  }
  // Helpers: TBH uses single-arg this for Unity getters
  var namePtr = methodNativePtr('UnityEngine', 'Object', 'get_name', 0);
  if (namePtr && !namePtr.isNull()) {
    try {
      replay.getName = new NativeFunction(namePtr, 'pointer', ['pointer']);
    } catch (e1) {}
  }
  var trPtr = methodNativePtr('UnityEngine', 'Component', 'get_transform', 0);
  if (trPtr && !trPtr.isNull()) {
    try {
      replay.getTransform = new NativeFunction(trPtr, 'pointer', ['pointer']);
    } catch (e3) {}
  }
  var parentPtr = methodNativePtr('UnityEngine', 'Transform', 'get_parent', 0);
  if (parentPtr && !parentPtr.isNull()) {
    try {
      replay.getParent = new NativeFunction(parentPtr, 'pointer', ['pointer']);
    } catch (e5) {}
  }

  // Drain press jobs on Unity main thread (EventSystem.Update) — required to avoid AV@0x0
  var esUpdateInfo = findMethodInfo('UnityEngine.EventSystems', 'EventSystem', 'Update', 0);
  var esUpdatePtr = methodPointerOrNull(esUpdateInfo);
  if (esUpdatePtr) {
    replay.eventSystemUpdatePtr = esUpdatePtr;
    try {
      Interceptor.attach(esUpdatePtr, {
        onEnter: function () {
          drainResolveJobs();
          drainPressJobs();
        },
      });
      state.mainThreadHooked = true;
    } catch (eEs) {
      state.mainThreadHooked = false;
      state.lastError = 'EventSystem.Update Hook 失败: ' + eEs;
    }
  } else {
    state.mainThreadHooked = false;
    state.lastError = '未找到 EventSystem.Update（回放无法安全切主线程）';
  }

  return !!(replay.buttonPress && replay.buttonPressInfo && state.mainThreadHooked);
}

function attachHooks() {
  try {
    if (!bindIl2Cpp()) {
      state.hooked = false;
      return fail(
        state.lastError ||
          '未找到 IL2CPP 导出（GameAssembly.dll）。进程已附加，但 UI Hook 不可用。'
      );
    }
    initUnityHelpers();
    var okAny = false;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Button', 'button') || okAny;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Toggle', 'toggle') || okAny;
    okAny = hookOnPointerClick('UnityEngine.UI', 'Dropdown', 'dropdown') || okAny;
    okAny = hookOnPointerClick('TMPro', 'TMP_Dropdown', 'dropdown') || okAny;
    var replayOk = setupReplayNatives();
    state.hooked = okAny;
    if (!okAny) {
      return fail('未能 Hook OnPointerClick（可能不是 uGUI，或程序集名不同）');
    }
    if (!replayOk) {
      state.lastError =
        state.lastError ||
        '已 Hook 录制，但主线程回放未就绪（缺少 Button.Press 或 EventSystem.Update）';
      return ok({ hooked: true, il2cpp: true, replay: false, warning: state.lastError });
    }
    return ok({ hooked: true, il2cpp: true, replay: true, mainThread: true });
  } catch (e) {
    state.hooked = false;
    return fail(String(e));
  }
}

function findByPath(hierarchyPath, componentType, siblingIndex) {
  var key = [hierarchyPath || '', componentType || '', String(siblingIndex || 0)].join('|');
  var cached = state.ptrByKey[key];
  if (cached && isAliveObject(cached)) return cached;
  if (cached) {
    try {
      delete state.ptrByKey[key];
    } catch (e) {}
  }

  // Cross-session: re-scan live UI tree by hierarchy_path (on Unity main thread).
  var found = NULL;
  if (state.mainThreadHooked) {
    found = queueResolveOnMainThread(hierarchyPath, componentType, siblingIndex, 4000);
  } else {
    try {
      found = findByPathLive(hierarchyPath, componentType, siblingIndex);
    } catch (eLive) {
      state.lastError = '路径重解析失败: ' + eLive;
      found = NULL;
    }
  }
  if (found && !found.isNull() && isAliveObject(found)) {
    try {
      state.ptrByKey[key] = found;
    } catch (eCache) {}
    return found;
  }
  return NULL;
}

function queueResolveOnMainThread(hierarchyPath, componentType, siblingIndex, timeoutMs) {
  var job = {
    hierarchyPath: hierarchyPath,
    componentType: componentType,
    siblingIndex: siblingIndex,
    done: false,
    result: NULL,
    error: null,
  };
  state.resolveJobs.push(job);
  var deadline = Date.now() + (timeoutMs || 4000);
  while (!job.done && Date.now() < deadline) {
    Thread.sleep(0.01);
  }
  if (!job.done) {
    try {
      var idx = state.resolveJobs.indexOf(job);
      if (idx >= 0) state.resolveJobs.splice(idx, 1);
    } catch (e0) {}
    state.lastError = '路径重解析超时（请保持游戏前台运行）';
    return NULL;
  }
  if (job.error) {
    state.lastError = job.error;
    return NULL;
  }
  return job.result || NULL;
}

function drainResolveJobs() {
  if (!state.resolveJobs.length) return;
  var job = state.resolveJobs.shift();
  if (!job) return;
  try {
    job.result = findByPathLive(job.hierarchyPath, job.componentType, job.siblingIndex);
    job.done = true;
  } catch (e) {
    job.error = String(e);
    job.result = NULL;
    job.done = true;
  }
}

function resolve(stableId) {
  try {
    var path = stableId && stableId.hierarchy_path;
    if (!path) return fail('hierarchy_path 为空');
    if (path === 'Unknown') return fail('录制路径无效(Unknown)，请重新录入该点击');
    var p = findByPath(path, stableId.component_type, stableId.sibling_index || 0);
    if (!p || p.isNull()) {
      return fail(
        '无法解析 UI 路径: ' +
          path +
          '（请确认 Frida 已连接、游戏停在录入时的界面，且控件层级未改动）'
      );
    }
    return ok({ ptr: p.toString(), resolved: true });
  } catch (e) {
    return fail(String(e));
  }
}

function drainPressJobs() {
  if (!state.pressJobs.length) return;
  var job = state.pressJobs.shift();
  if (!job) return;
  try {
    if (!isAliveObject(job.component)) {
      job.ok = false;
      job.error = '目标组件指针已失效，请重新录入';
      job.done = true;
      return;
    }
    if (!replay.buttonPress || !replay.buttonPressInfo || replay.buttonPressInfo.isNull()) {
      job.ok = false;
      job.error = 'Button.Press 未就绪';
      job.done = true;
      return;
    }
    replay.buttonPress(job.component, replay.buttonPressInfo);
    job.ok = true;
    job.invoked = 'Button.Press';
    job.done = true;
  } catch (e) {
    if (
      replay.buttonOnPointerClick &&
      replay.buttonOnPointerClickInfo &&
      replay.lastPointerEvent &&
      !replay.lastPointerEvent.isNull()
    ) {
      try {
        replay.buttonOnPointerClick(
          job.component,
          replay.lastPointerEvent,
          replay.buttonOnPointerClickInfo
        );
        job.ok = true;
        job.invoked = 'Button.OnPointerClick';
        job.done = true;
        return;
      } catch (e2) {
        job.ok = false;
        job.error = 'Press/OnPointerClick 失败: ' + e + ' / ' + e2;
        job.done = true;
        return;
      }
    }
    job.ok = false;
    job.error = 'Button.Press 失败: ' + e;
    job.done = true;
  }
}

function queuePressOnMainThread(component, timeoutMs) {
  if (!state.mainThreadHooked) {
    return fail('主线程回放未就绪（EventSystem.Update 未 Hook），请重新连接 Frida');
  }
  if (!isAliveObject(component)) {
    return fail('目标组件指针已失效，请重新录入');
  }
  var job = {
    component: component,
    done: false,
    ok: false,
    error: null,
    invoked: null,
  };
  state.pressJobs.push(job);
  var deadline = Date.now() + (timeoutMs || 3000);
  while (!job.done && Date.now() < deadline) {
    Thread.sleep(0.01);
  }
  if (!job.done) {
    try {
      var idx = state.pressJobs.indexOf(job);
      if (idx >= 0) state.pressJobs.splice(idx, 1);
    } catch (e0) {}
    return fail('主线程回放超时（游戏可能已暂停/卡死）。请保持游戏前台运行后重试');
  }
  if (!job.ok) return fail(job.error || '回放失败');
  return ok({ invoked: job.invoked || 'Button.Press' });
}

function invokeClick(stableId, button) {
  try {
    var r = resolve(stableId || {});
    if (!r.ok) return r;
    var component = findByPath(
      stableId.hierarchy_path,
      stableId.component_type || 'UnityEngine.UI.Button',
      stableId.sibling_index || 0
    );
    if (!isAliveObject(component)) {
      return fail('目标组件指针已失效，请重新录入该节点');
    }
    var pressed = queuePressOnMainThread(component, 3000);
    if (pressed.ok) {
      pressed.button = button || 'left';
    }
    return pressed;
  } catch (e) {
    return fail('回放点击失败: ' + e);
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
      try {
        stableId = JSON.parse(stableId);
      } catch (e) {}
    }
    return JSON.stringify(resolve(stableId || {}));
  },
  invokeclick: function (stableId, button) {
    if (typeof stableId === 'string') {
      try {
        stableId = JSON.parse(stableId);
      } catch (e) {}
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
      il2cppReady: state.il2cppReady,
      mainThreadHooked: state.mainThreadHooked,
      pressJobs: state.pressJobs.length,
      resolveJobs: state.resolveJobs.length,
      cachedPtrs: Object.keys(state.ptrByKey).length,
    });
  },
};
