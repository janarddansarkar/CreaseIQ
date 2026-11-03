from langchain_core.messages import AIMessage

from common import S, reply, safe_node
from config import STRINGS


def test_safe_node_records_exception():
    @safe_node
    def boom(state):
        raise ValueError("bad")
    out = boom({})
    assert out["error"].startswith("boom: ValueError: bad")


def test_safe_node_passes_result_through():
    @safe_node
    def ok(state):
        return {"x": 1}
    assert ok({}) == {"x": 1}


def test_S_uses_response_language_and_falls_back_to_default():
    assert S({"response_language": "hi"}, "error") == STRINGS["hi"]["error"]
    assert S({}, "error") == STRINGS["en"]["error"]
    assert S({"response_language": "xx"}, "error") == STRINGS["en"]["error"]


def test_reply_builds_terminal_update():
    out = reply({}, "answered", "hello", extra=1)
    assert out["status"] == "answered" and out["answer"] == "hello" and out["extra"] == 1
    assert isinstance(out["messages"][0], AIMessage) and out["messages"][0].content == "hello"
