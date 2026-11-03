import pytest
from pydantic import ValidationError

from api import ChatRequest, _sse


def test_valid_request():
    r = ChatRequest(message="hi", conversation_id="abc-123_X")
    assert r.response_language is None


@pytest.mark.parametrize("kw", [
    {"message": ""},
    {"message": "x" * 2001},
    {"message": "ok", "conversation_id": "bad id!"},
    {"message": "ok", "conversation_id": "a" * 65},
    {},
])
def test_invalid_requests(kw):
    with pytest.raises(ValidationError):
        ChatRequest(**kw)


def test_sse_framing():
    assert _sse("step", {"node": "x"}) == 'event: step\ndata: {"node": "x"}\n\n'
