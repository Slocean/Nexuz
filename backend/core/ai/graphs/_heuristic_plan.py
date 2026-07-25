"""Heuristic FlowSpec planner (offline / fallback). Imported by recipes."""

from __future__ import annotations

import re

from backend.core.ai.lc.structured import ClarifyQuestion, FlowSpec, PlanStep


def _extract_quoted(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"[「\"'“](.+?)[」\"'”]", text)]


def heuristic_plan_from_text(text: str) -> FlowSpec:
    """Lightweight fallback when structured output fails (tests / offline)."""
    t = (text or "").strip()
    steps: list[PlanStep] = []
    needs_locate = False
    locate_texts: list[str] = []
    clarify: list[ClarifyQuestion] = []
    lower = t.lower()

    # IM / WeChat-style send (params from utterance only)
    send_intent = any(
        k in t
        for k in (
            "发消息",
            "发给",
            "发送消息",
            "发一条",
            "发送一条",
            "发微信",
            "发送一条消息",
        )
    ) or bool(re.search(r"给.+发送", t))
    if send_intent:
        contact = ""
        m = re.search(r"发给\s*([^\s，,「\"'“]+?)(?:\s|发|送|消息|$)", t)
        if m:
            contact = m.group(1).strip()
        else:
            m = re.search(r"给\s*([^\s，,发「\"'“]+?)\s*(?:发|送)", t)
            if m:
                contact = m.group(1).strip()
        if not contact:
            clarify.append(
                ClarifyQuestion(
                    id="contact",
                    prompt="要发给谁？（联系人/会话名）",
                    choices=[],
                    allow_free_text=True,
                )
            )

        message = ""
        m = re.search(r"发送一条?\s*[「\"'“](.+?)[」\"'”]", t)
        if m:
            message = m.group(1).strip()
        if not message:
            m = re.search(r"(?:消息|内容)\s*[「\"'“](.+?)[」\"'”]", t)
            if m:
                message = m.group(1).strip()
        if not message:
            # 「发送一条消息：你好」/「消息: xxx」
            m = re.search(r"(?:消息|内容)\s*[：:]\s*(.+)$", t)
            if m:
                message = m.group(1).strip().strip("「」\"'")
        if not message:
            quoted = _extract_quoted(t)
            for q in quoted:
                if q and q != contact and len(q) <= 80:
                    message = q
                    break
        if not message:
            clarify.append(
                ClarifyQuestion(
                    id="message",
                    prompt="要发送的消息内容是？",
                    choices=[],
                    allow_free_text=True,
                )
            )

        run_at = ""
        m = re.search(r"(\d{1,2})\s*[点:：]\s*(\d{0,2})", t)
        if m and any(k in t for k in ("定时", "每天", "点执行", "到点", "分发")):
            hh, mm = m.group(1), m.group(2) or "00"
            run_at = f"{int(hh):02d}:{int(mm or 0):02d}"
        elif m and re.search(r"\d+\s*[点时].*(?:发|执行|运行)", t):
            hh, mm = m.group(1), m.group(2) or "00"
            run_at = f"{int(hh):02d}:{int(mm or 0):02d}"

        once = any(
            k in t for k in ("执行一次", "马上", "立刻", "立即", "现在发", "现在就")
        )
        want_schedule = bool(run_at) or (
            any(k in t for k in ("定时", "每天", "到点")) and not once
        )
        if once:
            want_schedule = False
            run_at = ""

        window_title = ""
        if "微信" in t or "wechat" in lower:
            window_title = "微信"  # only when user literally said the app name
        if not window_title:
            clarify.append(
                ClarifyQuestion(
                    id="window_title",
                    prompt="在哪个应用窗口发送？（请写出窗口标题）",
                    choices=[],
                    allow_free_text=True,
                )
            )

        if any(k in t for k in ("多个", "哪一个", "哪个联系人", "选一个")) and contact:
            clarify.append(
                ClarifyQuestion(
                    id="contact_pick",
                    prompt=f"请选择联系人「{contact}」的具体对象",
                    choices=[],
                    allow_free_text=True,
                )
            )

        # Incomplete params → clarify only; do not expand with invented defaults
        if clarify and (not contact or not message or not window_title):
            return FlowSpec(
                intent_summary=t[:80],
                needs_locate=False,
                locate_texts=[],
                clarify_questions=clarify,
                steps=[],
            )

        steps.append(
            PlanStep(
                action="call_skill",
                recipe="wechat_send_message",
                params={
                    "contact": contact,
                    "message": message,
                    "window_title": window_title,
                    "run_at": run_at,
                    "schedule": want_schedule,
                },
            )
        )
        return FlowSpec(
            intent_summary=t[:80],
            needs_locate=False,
            locate_texts=[],
            clarify_questions=[],
            steps=steps,
        )

    # find image / color pathways (B)
    if any(k in t for k in ("找图", "模板图", "图片点击", "按图片")):
        path = ""
        m = re.search(r"[「\"'](.+?\.(?:png|jpg|jpeg|bmp))[」\"']", t, re.I)
        if m:
            path = m.group(1)
        if not path:
            clarify.append(
                ClarifyQuestion(
                    id="template",
                    prompt="找图模板的文件路径是？",
                    choices=[],
                    allow_free_text=True,
                )
            )
            return FlowSpec(
                intent_summary=t[:80],
                steps=[],
                clarify_questions=clarify,
                needs_locate=False,
            )
        steps.append(
            PlanStep(
                action="recipe",
                recipe="find_image_click",
                params={"template": path, "path": path},
            )
        )
        return FlowSpec(intent_summary=t[:80], steps=steps, needs_locate=False)

    if any(k in t for k in ("取色点击", "按颜色", "颜色点击", "检测到颜色")):
        color = ""
        m = re.search(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", t)
        if m:
            color = m.group(0)
        if not color:
            clarify.append(
                ClarifyQuestion(
                    id="target_color",
                    prompt="要点击的目标颜色是？（如 #FF0000）",
                    choices=[],
                    allow_free_text=True,
                )
            )
            return FlowSpec(
                intent_summary=t[:80],
                steps=[],
                clarify_questions=clarify,
                needs_locate=False,
            )
        steps.append(
            PlanStep(
                action="recipe",
                recipe="color_click",
                params={"target_color": color},
            )
        )
        return FlowSpec(intent_summary=t[:80], steps=steps, needs_locate=False)

    # control flow
    m = re.search(r"(?:循环|重复)\s*(\d+)\s*次", t)
    if m:
        steps.append(
            PlanStep(
                action="recipe",
                recipe="loop_n",
                params={"times": int(m.group(1))},
            )
        )
    if any(k in t for k in ("如果出现", "若包含", "如果屏幕上有")):
        label = ""
        m2 = re.search(r"[「\"'](.+?)[」\"']", t)
        if m2:
            label = m2.group(1)
        steps.append(
            PlanStep(
                action="recipe",
                recipe="if_text",
                match_text=label or "确定",
                params={"match_text": label or "确定"},
            )
        )
    if ("try" in lower and "catch" in lower) or "捕获异常" in t or "出错时" in t:
        steps.append(PlanStep(action="recipe", recipe="try_catch_wrap"))

    # schedule (soft) — avoid matching 点一下; skip when 执行一次
    if not any(k in t for k in ("执行一次", "马上", "立刻", "立即")) and (
        any(k in t for k in ("定时", "每天", "点执行"))
        or re.search(r"\d+\s*[点时]\s*(?:\d+\s*分)?(?:执行|发送|运行)", t)
    ):
        steps.append(
            PlanStep(
                action="recipe",
                recipe="schedule_at",
                params={"trigger_type": "once"},
                note="定时触发",
            )
        )

    # window — title only from utterance, never invent an app name
    win_m = re.search(r"(?:激活|打开|等待)\s*([^\s，,]+)\s*窗口", t)
    title = ""
    if win_m:
        title = (win_m.group(1) or "").strip()
    elif "微信窗口" in t or (("激活" in t or "打开" in t) and "微信" in t and "窗口" in t):
        title = "微信"
    if title:
        steps.append(
            PlanStep(
                action="recipe",
                recipe="window_focus",
                params={"title": title},
            )
        )

    # delay
    cn_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    m = re.search(
        r"(?:等待|等到|等|wait|delay)\s*(\d+|[一二两三四五])\s*(秒|s|ms|毫秒|分钟)?",
        t,
        re.I,
    )
    if m:
        raw = m.group(1)
        n = cn_num.get(raw, None)
        if n is None:
            n = int(raw)
        unit = (m.group(2) or "秒").lower()
        if unit in ("ms", "毫秒"):
            ms = n
        elif unit in ("分钟", "min"):
            ms = n * 60_000
        else:
            ms = n * 1000
        steps.append(PlanStep(action="delay", params={"ms": ms}))

    typed = False
    m = re.search(r"输入密码\s+(\S+)", t)
    if m:
        steps.append(PlanStep(action="type_text", params={"text": m.group(1)}))
        typed = True
    m = re.search(r"输入邮箱\s+(\S+)", t)
    if m:
        steps.append(PlanStep(action="type_text", params={"text": m.group(1)}))
        typed = True
    if "输入密码" in t and not typed:
        steps.append(PlanStep(action="type_text", params={"text": "{{password}}"}))
        typed = True
    for m in re.finditer(
        r"(?:输入|type)\s*[「\"']([^「\"']+)[」\"']|(?:输入|type)\s*([^\s，,。；;再然后点击点按]+)",
        t,
        re.I,
    ):
        val = (m.group(1) or m.group(2) or "").strip()
        val = re.sub(r"(再|然后|后|并).*$", "", val).strip()
        if not val or val in ("密码", "邮箱"):
            continue
        if val.startswith("密码") or val.startswith("邮箱"):
            continue
        steps.append(PlanStep(action="type_text", params={"text": val}))
        typed = True
    if "hello" in lower and not any(s.action == "type_text" for s in steps):
        if not any(s.action == "delay" for s in steps):
            steps.append(PlanStep(action="delay", params={"ms": 1000}))
        steps.append(PlanStep(action="type_text", params={"text": "hello"}))

    if any(k in t for k in ("回车", "enter", "按回车")):
        steps.append(PlanStep(action="key_press", params={"key": "enter"}))
    elif re.search(r"按\s*tab|按一下\s*tab|\btab\b", t, re.I):
        steps.append(PlanStep(action="key_press", params={"key": "tab"}))

    m = re.search(r"等到?(?:出现)?(?:文字)?[「\"'](.+?)[」\"']", t)
    wait_label = m.group(1) if m else None

    click_labels: list[str] = []
    for m in re.finditer(r"(?:点击|点一下|点)\s*[「\"'](.+?)[」\"']", t):
        click_labels.append(m.group(1).strip())
    if not click_labels:
        m = re.search(
            r"(?:点击|点一下|点)\s*(?:屏幕上的|文字)?[「\"']?([\w\u4e00-\u9fff]+)[」\"']?",
            t,
        )
        if m:
            label = m.group(1).strip()
            if label not in ("屏幕上的", "文字", "一下"):
                click_labels.append(label)
    if not click_labels and ("点击" in t or re.search(r"点(?!击)", t)):
        for m in re.finditer(r"[「\"'](.+?)[」\"']", t):
            click_labels.append(m.group(1).strip())

    if wait_label:
        steps.append(
            PlanStep(
                action="recipe",
                recipe="wait_text",
                params={"match_text": wait_label},
                match_text=wait_label,
            )
        )

    for label in click_labels:
        # Bound OCR chain — no live locate panel
        steps.append(
            PlanStep(action="ocr_click", match_text=label, recipe="ocr_click_chain")
        )

    if not steps:
        steps = [PlanStep(action="delay", params={"ms": 1000})]

    return FlowSpec(
        intent_summary=t[:80],
        needs_locate=needs_locate,
        locate_texts=locate_texts,
        clarify_questions=clarify,
        steps=steps,
    )
