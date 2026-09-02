"""usage_tracker：按轮次累计、LangChain 响应形状提取、轮次外零副作用。"""

from __future__ import annotations

from backend.core.ai import usage_tracker as ut


class _MsgWithMetadata:
    """LangChain AIMessage usage_metadata 形状。"""

    def __init__(self, inp, out, total):
        self.usage_metadata = {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": total,
        }


class _MsgWithResponseMetadata:
    """openai token_usage 形状（response_metadata.token_usage）。"""

    def __init__(self, prompt, completion):
        self.response_metadata = {
            "token_usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        }


class _MsgNoUsage:
    pass


class _Gen:
    def __init__(self, msg):
        self.message = msg


class _Result:
    """LangChain LLMResult 形状。"""

    def __init__(self, generations=None, llm_output=None):
        self.generations = generations or []
        self.llm_output = llm_output or {}


def _zero(d: dict) -> bool:
    return d["calls"] == 0 and d["input_tokens"] == 0 and d["output_tokens"] == 0


def test_outside_turn_record_is_noop():
    ut.record({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    assert ut.callbacks() == []
    assert ut.runnable_config() is None
    assert _zero(ut.finish_turn())


def test_turn_accumulation_and_nesting():
    ut.start_turn()
    ut.record({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    snap = ut.snapshot()
    assert snap["calls"] == 1 and snap["input_tokens"] == 100

    ut.record({"input_tokens": 50, "output_tokens": 30, "total_tokens": 80})
    assert ut.snapshot()["input_tokens"] == 150

    usage = ut.finish_turn()
    assert usage == {"calls": 2, "no_usage": 0, "input_tokens": 150, "output_tokens": 50, "total_tokens": 200}
    assert _zero(ut.finish_turn())  # 栈已空


def test_no_usage_counts_calls_but_flags():
    ut.start_turn()
    ut.record(None)
    ut.record({"input_tokens": None})
    usage = ut.finish_turn()
    assert usage["calls"] == 2 and usage["no_usage"] == 2
    assert usage["input_tokens"] == 0


def test_extract_shapes():
    m1 = ut.extract_message_usage(_MsgWithMetadata(7, 3, 10))
    assert m1 == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    m2 = ut.extract_message_usage(_MsgWithResponseMetadata(8, 2))
    assert m2["input_tokens"] == 8 and m2["output_tokens"] == 2
    assert ut.extract_message_usage(_MsgNoUsage()) is None
    assert ut.extract_message_usage("not a message") is None


def test_callback_on_llm_end_inside_turn():
    ut.start_turn()
    cbs = ut.callbacks()
    assert len(cbs) == 1
    cbs[0].on_llm_end(_Result(generations=[[_Gen(_MsgWithMetadata(10, 5, 15))]]))
    cbs[0].on_llm_end(_Result(llm_output={"token_usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}))
    usage = ut.finish_turn()
    assert usage["calls"] == 2
    assert usage["input_tokens"] == 14 and usage["output_tokens"] == 6 and usage["total_tokens"] == 20


def test_callback_ignores_errors():
    ut.start_turn()
    cbs = ut.callbacks()
    cbs[0].on_llm_end(None)  # 非 LLMResult → 记 no_usage，不抛
    cbs[0].on_llm_end(_Result(generations=[[object()]]))
    usage = ut.finish_turn()
    assert usage["calls"] == 2 and usage["no_usage"] == 2
