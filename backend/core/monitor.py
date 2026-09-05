"""后台条件监控：监控线程 + 事件队列 + 长轮询唤醒。

与 schedule_trigger（到点触发整条流程）互补：监控只观察条件、记录事件，
不触发任何东西。调用方决定何时来取——外部 AI 用 monitor_wait 长轮询
（单次 ≤60 秒，事件一出现调用立即返回，等效「唤醒」），或配合客户端定时
任务周期性 monitor_check；流程内则可以先 monitor_start 再在循环里取事件，
边执行边监听。

事件语义（边沿触发）：条件从假变真记一次事件（fire=edge）；条件持续为真
时，refire_ms>0 则每隔 refire_ms 再记一次（fire=refire），0 表示不重复；
启动后首次检查即为真时是否立刻记事件由 fire_on_start 决定。

持久化：监控规格随 monitors/monitors.json 保存并在应用启动时恢复；事件
只存内存环形队列（默认 100 条），应用重启后清空（事件 id 水位保留，
恢复后新事件 id 接着增长，调用方旧游标不会漏事件）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MONITOR_TYPES = ("process", "window", "file", "screen_text", "screen_color")
_ON_ALLOWED: dict[str, tuple[str, ...]] = {
    "process": ("appear", "disappear"),
    "window": ("appear", "disappear"),
    "file": ("appear", "disappear", "change"),
    "screen_text": ("appear", "disappear"),
    "screen_color": ("appear", "disappear"),
}
_LABEL_ON = {"appear": "出现", "disappear": "消失", "change": "变化"}

_MAX_MONITORS = 32
_MAX_EVENTS_CAP = 500
_DEFAULT_MAX_EVENTS = 100
_MIN_POLL_MS = 250
_MAX_EXPIRE_S = 7 * 86400
_WAIT_SLICE_S = 0.2

_manager: "MonitorManager | None" = None
_manager_lock = threading.Lock()


def get_monitor_manager() -> "MonitorManager":
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = MonitorManager()
        return _manager


def _monitors_file() -> Path:
    from backend.paths import get_data_dir

    return get_data_dir(create=True) / "monitors" / "monitors.json"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并归一化监控规格；配置错误直接抛 ValueError（启动即失败）。"""
    raw = raw if isinstance(raw, dict) else {}
    mtype = str(raw.get("monitor_type") or "").strip()
    if mtype not in MONITOR_TYPES:
        raise ValueError(f"未知监控类型: {mtype or '（空）'}（支持 {'、'.join(MONITOR_TYPES)}）")
    try:
        params = json.loads(json.dumps(raw.get("params") if isinstance(raw.get("params"), dict) else {}, ensure_ascii=False))
    except (TypeError, ValueError):
        params = dict(raw.get("params") or {})
    on = str(params.get("on") or "appear").strip().lower() or "appear"
    if on not in _ON_ALLOWED[mtype]:
        raise ValueError(
            f"{mtype} 监控不支持 on={on}（支持 {'、'.join(_ON_ALLOWED[mtype])}）"
        )
    params["on"] = on

    def _num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            val = float(raw.get(key) if raw.get(key) is not None else default)
        except (TypeError, ValueError):
            val = float(default)
        return max(lo, min(hi, val))

    return {
        "monitor_type": mtype,
        "params": params,
        "poll_interval_ms": int(_num("poll_interval_ms", 1000, _MIN_POLL_MS, 3600_000)),
        "refire_ms": int(_num("refire_ms", 0, 0, 86_400_000)),
        "fire_on_start": _as_bool(raw.get("fire_on_start"), False),
        "expire_seconds": _num("expire_seconds", 3600, 0, _MAX_EXPIRE_S),
        "max_events": int(_num("max_events", _DEFAULT_MAX_EVENTS, 1, _MAX_EVENTS_CAP)),
        "toast": _as_bool(raw.get("toast"), False),
    }


def spec_summary(spec: dict[str, Any]) -> str:
    mtype = str(spec.get("monitor_type") or "")
    params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
    on = str(params.get("on") or "appear")
    label = _LABEL_ON.get(on, on)
    if mtype == "process":
        pid = _as_int(params.get("pid"), 0)
        target = f"pid={pid}" if pid > 0 else f"name='{params.get('process_name') or ''}'"
        return f"进程 {target} {label}"
    if mtype == "window":
        target = (
            str(params.get("title") or "").strip()
            or str(params.get("process_name") or "").strip()
            or str(params.get("class_name") or "").strip()
            or "?"
        )
        return f"窗口 '{target}' {label}"
    if mtype == "file":
        return f"文件 {params.get('file_path') or '?'} {label}"
    if mtype == "screen_text":
        return f"屏幕文字 '{params.get('expect_text') or '?'}' {label}"
    if mtype == "screen_color":
        return f"屏幕颜色 {params.get('target_color') or '?'} {label}"
    return mtype


# ---------------------------------------------------------------------------
# 条件求值：返回 (matched, detail, data, error)；配置错误抛 ValueError。
# state 为监控实例的可变状态袋（如文件变化基线），跨检查保持。
# ---------------------------------------------------------------------------


def _eval_process(params: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str, dict, str]:
    name = str(params.get("process_name") or "").strip()
    pid = _as_int(params.get("pid"), 0)
    on = str(params.get("on") or "appear")
    if pid > 0:
        try:
            import psutil
        except ImportError:
            return False, "", {}, "psutil 未安装，无法按 PID 监控进程"
        exists = bool(psutil.pid_exists(pid))
        pname = ""
        if exists:
            try:
                pname = str(psutil.Process(pid).name() or "")
            except Exception:
                pname = ""
        data = {"pid": pid, "name": pname, "exists": exists}
        detail = f"pid {pid} {'存在' if exists else '已退出'}{f'（{pname}）' if pname else ''}"
    elif name:
        from backend.blocks._os_ops import list_processes

        res = list_processes(name, 50)
        if res.get("error"):
            return False, "", {}, str(res.get("error"))
        items = res.get("items") or []
        exists = bool(items)
        data = {
            "exists": exists,
            "count": len(items),
            "pids": [item.get("pid") for item in items[:5]],
            "names": sorted({str(item.get("name") or "") for item in items})[:5],
        }
        detail = f"'{name}' {'存在' if exists else '不存在'}（{len(items)} 个进程）"
    else:
        raise ValueError("进程监控需要填写 process_name 或 pid")
    matched = exists if on == "appear" else not exists
    return matched, detail, data, ""


def _eval_window(params: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str, dict, str]:
    from backend.blocks._window_ops import match_or_error

    on = str(params.get("on") or "appear")
    hwnd, info, err = match_or_error(params)
    if hwnd:
        data = {
            "found": True,
            "title": str(info.get("title") or ""),
            "pid": int(info.get("pid") or 0),
            "process_name": str(info.get("process_name") or ""),
        }
        return (on == "appear"), f"窗口存在: {data['title'][:60]}", data, ""
    # 「未找到窗口」是正常观察结果；其余报错是配置问题（非 Windows / 未选窗口）。
    if err and not err.startswith("未找到"):
        return False, "", {}, err
    return (on == "disappear"), f"窗口不存在（{err}）", {"found": False}, ""


def _eval_file(params: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str, dict, str]:
    raw = str(params.get("file_path") or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("文件监控需要填写 file_path")
    path = Path(raw)
    on = str(params.get("on") or "appear")
    exists = path.exists()
    mtime = 0
    size = 0
    if exists:
        try:
            st = path.stat()
            mtime = int(st.st_mtime)
            size = int(st.st_size)
        except OSError:
            exists = False
    data = {"path": str(path), "exists": exists, "mtime": mtime, "size": size}
    if on == "change":
        baseline = state.get("baseline")
        state["baseline"] = (mtime, size)
        if baseline is None:
            return False, f"变化基线已记录: {path.name}", data, ""
        changed = tuple(baseline) != (mtime, size)
        return changed, f"{path.name} {'已变化' if changed else '无变化'}（{size}B）", data, ""
    if on == "disappear":
        return (not exists), ("文件已消失" if not exists else f"文件仍存在（{size}B）"), data, ""
    return exists, (f"文件已出现（{size}B）" if exists else "文件不存在"), data, ""


def _eval_screen(mtype: str, params: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str, dict, str]:
    from backend.blocks.wait_until import _check as wait_until_check

    wait_type = "text" if mtype == "screen_text" else "color"
    matched, detail, coords = wait_until_check({**params, "wait_type": wait_type}, {})
    on = str(params.get("on") or "appear")
    if on == "disappear":
        matched = not matched
        detail = f"（取反）{detail}"
    return bool(matched), detail, dict(coords or {}), ""


def evaluate_condition(spec: dict[str, Any], state: dict[str, Any] | None = None) -> tuple[bool, str, dict, str]:
    state = state if isinstance(state, dict) else {}
    mtype = str(spec.get("monitor_type") or "")
    params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
    if mtype == "process":
        return _eval_process(params, state)
    if mtype == "window":
        return _eval_window(params, state)
    if mtype == "file":
        return _eval_file(params, state)
    if mtype in ("screen_text", "screen_color"):
        return _eval_screen(mtype, params, state)
    raise ValueError(f"未知监控类型: {mtype}")


class Monitor:
    def __init__(self, monitor_id: str, spec: dict[str, Any], origin: str = ""):
        self.id = monitor_id
        self.spec = spec
        self.origin = str(origin or "")
        self.created_at = time.time()
        self.status = "running"
        self.level: bool | None = None
        self.last_fire_ts = 0.0
        self.last_error = ""
        self.check_count = 0
        self.events: deque[dict[str, Any]] = deque(maxlen=int(spec.get("max_events") or _DEFAULT_MAX_EVENTS))
        self.next_event_id = 1
        self.stop_flag = threading.Event()
        self.state: dict[str, Any] = {}
        self.thread: threading.Thread | None = None

    def summary(self) -> dict[str, Any]:
        last = self.events[-1] if self.events else None
        return {
            "monitor_id": self.id,
            "monitor_type": self.spec.get("monitor_type"),
            "spec": spec_summary(self.spec),
            "status": self.status,
            "origin": self.origin,
            "created_at_text": datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            "poll_interval_ms": self.spec.get("poll_interval_ms"),
            "refire_ms": self.spec.get("refire_ms"),
            "expire_seconds": self.spec.get("expire_seconds"),
            "max_events": self.spec.get("max_events"),
            "check_count": self.check_count,
            "event_count": len(self.events),
            "last_event_id": self.next_event_id - 1,
            "last_event_text": f"{last['ts_text']} {last['detail']}" if last else "",
            "last_error": self.last_error,
        }


class MonitorManager:
    def __init__(self) -> None:
        self._monitors: dict[str, Monitor] = {}
        self._lock = threading.RLock()
        self._new_event = threading.Condition(self._lock)
        self._last_persist_ts = 0.0

    # -- 生命周期 ------------------------------------------------------------

    def start_monitor(
        self,
        spec: dict[str, Any],
        *,
        monitor_id: str = "",
        origin: str = "",
        persist: bool = True,
        resume_event_id: int = 0,
    ) -> dict[str, Any]:
        norm = normalize_spec(spec)
        state: dict[str, Any] = {}
        # 启动即试检一次：配置错误（缺参数/非法区域/非 Windows）当场报错，
        # 而不是静默空转到超时；试检状态（如文件基线）直接复用，避免启动瞬间误触发。
        _matched, _detail, _data, probe_error = evaluate_condition(norm, state)
        if probe_error:
            raise ValueError(probe_error)
        mid = str(monitor_id or "").strip() or f"mon_{int(time.time() * 1000):x}"
        with self._lock:
            old = self._monitors.pop(mid, None)
            if old is not None:
                old.stop_flag.set()
                old.status = "stopped"
            if old is None and len(self._monitors) >= _MAX_MONITORS:
                raise ValueError(f"监控数量已达上限（{_MAX_MONITORS}），请先 monitor_stop 清理")
            mon = Monitor(mid, norm, origin)
            mon.state = state
            mon.next_event_id = max(1, int(resume_event_id or 0) + 1)
            self._monitors[mid] = mon
        mon.thread = threading.Thread(
            target=self._loop, args=(mon,), daemon=True, name=f"nexuz-monitor-{mid}"
        )
        mon.thread.start()
        if persist:
            self._persist()
        return {"monitor_id": mid, "status": "running", "spec": spec_summary(norm)}

    def stop_monitor(self, monitor_id: str) -> bool:
        with self._lock:
            mon = self._monitors.pop(str(monitor_id or "").strip(), None)
            if mon is None:
                return False
            mon.stop_flag.set()
            mon.status = "stopped"
            self._new_event.notify_all()
        self._persist()
        return True

    def stop_all(self) -> None:
        with self._lock:
            mons = list(self._monitors.values())
            for mon in mons:
                mon.stop_flag.set()
                mon.status = "stopped"
            self._monitors.clear()
            self._new_event.notify_all()

    # -- 事件读取 ------------------------------------------------------------

    def get_status(self, monitor_id: str) -> dict[str, Any] | None:
        with self._lock:
            mon = self._monitors.get(str(monitor_id or "").strip())
            return mon.summary() if mon else None

    def list_monitors(self) -> list[dict[str, Any]]:
        with self._lock:
            return [mon.summary() for mon in self._monitors.values()]

    def _collect_locked(self, mon: Monitor, since_event_id: int, limit: int) -> list[dict[str, Any]]:
        out = [dict(ev) for ev in mon.events if int(ev.get("id") or 0) > since_event_id]
        return out[: max(1, min(20, int(limit or 20)))]

    def drain_events(
        self, monitor_id: str, *, since_event_id: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        mid = str(monitor_id or "").strip()
        with self._lock:
            mon = self._monitors.get(mid)
            if mon is None:
                return self._missing_result(mid, since_event_id)
            events = self._collect_locked(mon, int(since_event_id or 0), limit)
            status = mon.status
        if events:
            # 投递即持久化 id 水位：崩溃/重启后恢复的新事件 id 必定高于
            # 调用方已消费过的游标，避免"游标超前、等待被永久跳过"。
            self._persist()
        return {
            "got": bool(events),
            "count": len(events),
            "events": events,
            "last_event_id": int(events[-1]["id"]) if events else int(since_event_id or 0),
            "status": status,
            "error": "",
        }

    def wait_events(
        self,
        monitor_id: str,
        *,
        since_event_id: int = 0,
        timeout_s: float = 30.0,
        limit: int = 20,
        should_stop: Callable[[], bool] | None = None,
        cooperate: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """长轮询：有事件立即返回；否则等到超时/监控停活。cooperate 与
        should_stop 在锁外调用（流程暂停可挂起这里），停止按钮能尽快穿透。"""
        mid = str(monitor_id or "").strip()
        with self._lock:
            mon = self._monitors.get(mid)
        if mon is None:
            return self._missing_result(mid, since_event_id)
        deadline = time.monotonic() + max(0.0, float(timeout_s or 0))
        status = "running"
        while True:
            with self._lock:
                events = self._collect_locked(mon, int(since_event_id or 0), limit)
                status = mon.status
            if events:
                self._persist()  # 投递即持久化 id 水位（见 drain_events）
                return {
                    "got": True,
                    "count": len(events),
                    "events": events,
                    "last_event_id": int(events[-1]["id"]),
                    "status": status,
                    "error": "",
                }
            if status != "running":
                return {
                    "got": False,
                    "count": 0,
                    "events": [],
                    "last_event_id": int(since_event_id or 0),
                    "status": status,
                    "error": f"监控已{'过期' if status == 'expired' else '停止'}，无新事件",
                }
            if should_stop is not None and should_stop():
                raise InterruptedError("流程已停止")
            if cooperate is not None:
                cooperate()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "got": False,
                    "count": 0,
                    "events": [],
                    "last_event_id": int(since_event_id or 0),
                    "status": status,
                    "error": "等待超时，期间无新事件",
                    "timed_out": True,
                }
            with self._lock:
                self._new_event.wait(timeout=min(_WAIT_SLICE_S, remaining))

    @staticmethod
    def _missing_result(monitor_id: str, since_event_id: int) -> dict[str, Any]:
        return {
            "got": False,
            "count": 0,
            "events": [],
            "last_event_id": int(since_event_id or 0),
            "status": "missing",
            "error": f"监控不存在: {monitor_id or '（空）'}（可能已被停止/过期；应用重启后事件清空，可 monitor_list 查看现存监控）",
        }

    # -- 检查线程 ------------------------------------------------------------

    def _loop(self, mon: Monitor) -> None:
        spec = mon.spec
        poll_s = max(0.25, float(spec.get("poll_interval_ms") or 1000) / 1000.0)
        refire_s = max(0.0, float(spec.get("refire_ms") or 0) / 1000.0)
        expire_s = float(spec.get("expire_seconds") or 0)
        started = time.monotonic()
        deadline = started + expire_s if expire_s > 0 else None
        fire_on_start = bool(spec.get("fire_on_start"))
        while not mon.stop_flag.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                with self._lock:
                    mon.status = "expired"
                    self._new_event.notify_all()
                break
            try:
                matched, detail, data, error = evaluate_condition(spec, mon.state)
                with self._lock:
                    mon.check_count += 1
                    mon.last_error = error
                    if not error:
                        first = mon.level is None
                        fire = ""
                        if matched:
                            if first:
                                fire = "start" if fire_on_start else ""
                            elif not mon.level:
                                fire = "edge"
                            elif refire_s > 0 and time.time() - mon.last_fire_ts >= refire_s:
                                fire = "refire"
                        mon.level = matched
                        if fire:
                            self._append_event_locked(mon, fire, detail, data)
            except Exception as exc:  # 条件求值异常（分辨率变化致区域失效等）：记录并继续
                with self._lock:
                    mon.last_error = str(exc)
            end = time.monotonic() + poll_s
            while not mon.stop_flag.is_set():
                remain = end - time.monotonic()
                if remain <= 0:
                    break
                mon.stop_flag.wait(min(0.1, remain))

    def _append_event_locked(
        self, mon: Monitor, fire: str, detail: str, data: dict[str, Any]
    ) -> None:
        event = {
            "id": mon.next_event_id,
            "monitor_id": mon.id,
            "type": mon.spec.get("monitor_type"),
            "fire": fire,
            "ts": round(time.time(), 3),
            "ts_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "detail": str(detail or "")[:200],
            "data": data if isinstance(data, dict) else {},
        }
        mon.next_event_id += 1
        mon.events.append(event)
        mon.last_fire_ts = time.time()
        self._new_event.notify_all()
        if time.time() - self._last_persist_ts >= 10.0:
            self._persist()  # 无人取件时限流推进水位，重启后 id 不倒退
        if mon.spec.get("toast"):
            threading.Thread(
                target=self._toast, args=(mon.id, event["detail"]), daemon=True, name="nexuz-monitor-toast"
            ).start()

    @staticmethod
    def _toast(monitor_id: str, detail: str) -> None:
        try:
            from backend.blocks.notify import handler as notify_handler

            notify_handler(
                {
                    "title": f"Nexuz 监控 · {monitor_id}",
                    "message": str(detail or "")[:120],
                    "play_sound": "false",
                },
                {},
            )
        except Exception:
            pass

    # -- 持久化 ---------------------------------------------------------------

    def _persist(self) -> None:
        rows = []
        with self._lock:
            for mon in self._monitors.values():
                rows.append(
                    {
                        "monitor_id": mon.id,
                        "origin": mon.origin,
                        "created_at": mon.created_at,
                        "last_event_id": mon.next_event_id - 1,
                        "spec": mon.spec,
                    }
                )
        try:
            path = _monitors_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            self._last_persist_ts = time.time()
        except OSError as exc:
            logger.warning("无法写入后台监控: %s", exc)

    def restore(self) -> int:
        """应用启动时恢复监控规格（事件清空，id 水位接续）。返回恢复条数。"""
        path = _monitors_file()
        if not path.is_file():
            return 0
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("无法读取后台监控: %s", exc)
            return 0
        if not isinstance(rows, list):
            return 0
        restored = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("monitor_id") or "").strip()
            spec = row.get("spec") if isinstance(row.get("spec"), dict) else None
            if not mid or spec is None:
                continue
            try:
                self.start_monitor(
                    spec,
                    monitor_id=mid,
                    origin=str(row.get("origin") or ""),
                    persist=False,
                    resume_event_id=_as_int(row.get("last_event_id"), 0),
                )
                restored += 1
            except Exception as exc:
                logger.warning("恢复监控失败 %s: %s", mid, exc)
        if restored:
            self._persist()
        return restored
