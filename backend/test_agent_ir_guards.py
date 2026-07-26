"""Guards for UnderstandIR coercion, placeholder goals, and coverage semantics."""

from __future__ import annotations

from backend.core.ai.graphs.agent_ir import (
    UnderstandIR,
    build_task_contract,
    evaluate_task_coverage,
    gap_from_ir,
)


def test_understand_ir_coerces_string_goals():
    uir = UnderstandIR.model_validate(
        {
            "intent_tag": "other",
            "slots": {"window_title": "微信"},
            "missing": [],
            "goals": ["打开微信", "点击通讯录"],
        }
    )
    assert len(uir.goals) == 2
    assert uir.goals[0].action == "打开微信"
    assert uir.slots["window_title"] == "微信"


def test_build_task_contract_drops_placeholder_goals():
    contract = build_task_contract(
        "打开微信给通讯录的mom发送一条消息：1",
        [
            {
                "id": "goal_1",
                "action": "activate_window",
                "target": "微信",
                "required_ops": ["activate"],
                "capability_gap": "none",
            },
            {
                "id": "goal_3",
                "action": "action_2",
                "target": "mom",
                "required_ops": ["ocr_click"],
                "capability_gap": "capability_gap",
            },
            {
                "id": "id_4",
                "action": "action_4",
                "target": "target_4",
                "value": "value_4",
                "completion": "completion_4",
                "required_ops": [],
                "capability_gap": "capabilability_gap",
            },
            {
                "id": "goal_5",
                "action": "action_5",
                "target": "target_        _5",
                "value": "value_5",
                "required_ops": [],
                "capability_gap": "capability_gap",
            },
        ],
    )
    ids = [g.id for g in contract.goals]
    assert ids == ["goal_1", "goal_3"]
    assert contract.goals[0].capability_gap == ""
    assert contract.goals[1].capability_gap == ""
    assert contract.goals[1].action == "mom"


def test_coverage_empty_goals_not_complete():
    coverage = evaluate_task_coverage(
        {"summary": "打开微信发消息", "goals": []},
        {"steps": [{"op": "activate", "a": {"window": "微信"}}]},
        utterance="打开微信发消息",
    )
    assert coverage["complete"] is False
    assert "缺少任务目标" in coverage["missing"]


def test_coverage_none_gap_not_warning():
    contract = build_task_contract(
        "打开微信",
        [
            {
                "id": "g1",
                "action": "activate",
                "target": "微信",
                "required_ops": ["activate"],
                "capability_gap": "none",
            }
        ],
    )
    coverage = evaluate_task_coverage(
        contract,
        {"steps": [{"op": "activate", "a": {"window": "微信"}}]},
    )
    assert coverage["complete"] is True
    assert coverage["capability_gaps"] == []


def test_gap_from_ir_folds_capability_gaps():
    gap = gap_from_ir(
        {"steps": [{"op": "activate", "a": {"window": "微信"}}]},
        {},
        intent="打开微信",
        task_contract={
            "summary": "打开微信",
            "goals": [
                {
                    "id": "g1",
                    "action": "activate",
                    "target": "微信",
                    "required_ops": ["activate"],
                    "capability_gap": "无法启动应用",
                }
            ],
        },
    )
    assert gap["complete"] is False
    assert gap["capability_gaps"]


def test_block_name_ops_alias_no_fake_gap():
    """Log 30da62b9: window_activate/type_text/key_press are aliases, not gaps."""
    contract = build_task_contract(
        "打开微信给通讯录的mom发送一条消息：1",
        [
            {
                "id": "goal_1",
                "action": "open_and_search_contact",
                "target": "微信",
                "value": "mom",
                "required_ops": ["window_activate", "ocr_click"],
            },
            {
                "id": "goal_2",
                "action": "send_message_text_and_submit",
                "target": "mom",
                "value": "1",
                "required_ops": ["type_text", "key_press"],
            },
        ],
    )
    assert contract.goals[0].required_ops == ["activate", "ocr_click"]
    assert contract.goals[0].capability_gap == ""
    assert contract.goals[1].required_ops == ["type", "key"]
    assert contract.goals[1].capability_gap == ""
    # Also recover when aliases were already parked in capability_gap text.
    recovered = build_task_contract(
        "打开微信",
        [
            {
                "id": "goal_2",
                "action": "send_message_text_and_submit",
                "target": "mom",
                "value": "1",
                "required_ops": [],
                "capability_gap": "执行器不支持 opcode：type_text, key_press",
            }
        ],
    )
    assert recovered.goals[0].required_ops == ["type", "key"]
    assert recovered.goals[0].capability_gap == ""
    coverage = evaluate_task_coverage(
        contract,
        {
            "steps": [
                {"op": "activate", "a": {"window": "微信"}},
                {"op": "ocr_click", "a": {"text": "mom"}},
                {"op": "type", "a": {"text": "1"}},
                {"op": "key", "a": {"keys": "Enter"}},
            ]
        },
    )
    assert coverage["complete"] is True
    assert coverage["capability_gaps"] == []


def test_consecutive_ocr_click_goals_share_one_ir_step():
    """Log 45117d36: find+click mom both need ocr_click; one IR step covers both."""
    contract = build_task_contract(
        "打开微信给通讯录的mom发送一条消息：1",
        [
            {
                "id": "activate_wechat",
                "action": "激活微信窗口",
                "target": "微信",
                "required_ops": ["activate"],
            },
            {
                "id": "find_contact_mom",
                "action": "OCR识别通讯录中的mom",
                "target": "mom",
                "required_ops": ["ocr_click"],
            },
            {
                "id": "click_contact_mom",
                "action": "点击mom进入聊天窗口",
                "target": "mom的坐标位置",
                "value": "{{ocr_recognize_e23de3f1.x}},{{ocr_recognize_e23de3f1.y}}",
                "required_ops": ["ocr_click"],
            },
            {
                "id": "type_message",
                "action": "输入消息内容",
                "target": "聊天输入框",
                "value": "1",
                "required_ops": ["type"],
            },
            {
                "id": "send_message",
                "action": "按下回车发送消息",
                "target": "聊天输入框",
                "value": "enter",
                "required_ops": ["key"],
            },
        ],
    )
    assert "{{" not in contract.goals[2].value
    coverage = evaluate_task_coverage(
        contract,
        {
            "steps": [
                {"op": "activate", "a": {"window": "微信"}},
                {"op": "ocr_click", "a": {"text": "mom"}},
                {"op": "type", "a": {"text": "1"}},
                {"op": "key", "a": {"key": "enter"}},
            ]
        },
    )
    assert coverage["complete"] is True
    by_id = {g["id"]: g for g in coverage["goals"]}
    assert by_id["find_contact_mom"]["covered"] is True
    assert by_id["click_contact_mom"]["covered"] is True
    assert by_id["click_contact_mom"]["matched_steps"] == [2]


def test_semantic_goals_infer_ops_and_cover_plan():
    """Log 1f49ef23: open_app/select_contact/send_message without required_ops."""
    contract = build_task_contract(
        "打开微信给通讯录的mom发送一条消息：1",
        [
            {"id": "g1", "action": "open_app", "target": "微信", "required_ops": []},
            {"id": "g2", "action": "select_contact", "target": "mom", "required_ops": []},
            {"id": "g3", "action": "send_message", "target": "", "value": "1", "required_ops": []},
        ],
    )
    assert "activate" in contract.goals[0].required_ops
    assert "ocr_click" in contract.goals[1].required_ops
    assert "type" in contract.goals[2].required_ops
    assert "key" in contract.goals[2].required_ops
    coverage = evaluate_task_coverage(
        contract,
        {
            "steps": [
                {"op": "activate", "a": {"window": "微信"}},
                {"op": "ocr_click", "a": {"text": "通讯录"}},
                {"op": "ocr_click", "a": {"text": "mom"}},
                {"op": "type", "a": {"text": "1"}},
                {"op": "key", "a": {"keys": "Enter"}},
            ]
        },
    )
    assert coverage["complete"] is True
    assert not any("未声明" in m for m in coverage["missing"])
