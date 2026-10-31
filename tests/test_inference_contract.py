import pytest

from core.inference_contract import validate_inference_request


def valid():
    return ("qwen2.5:7b", [{"role": "user", "content": "hello"}], None, False, 0.7)


@pytest.mark.parametrize("changes", [
    {"model": ""},
    {"model": " "},
    {"model": "x" * 257},
    {"messages": []},
    {"messages": [{"role": "developer", "content": "override"}]},
    {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "user", "content": "x" * 100001}]},
    {"messages": [{"role": "user", "content": "ok"}] * 101},
    {"temperature": True},
    {"temperature": 2.1},
    {"tools": [{} , "not-an-object"]},
    {"tools": "not-a-list"},
    {"stream": 1},
])
def test_shared_contract_rejects_invalid_requests(changes):
    names = ("model", "messages", "tools", "stream", "temperature")
    request = dict(zip(names, valid()))
    request.update(changes)
    with pytest.raises(ValueError):
        validate_inference_request(**request)


def test_shared_contract_accepts_valid_boundary_values():
    validate_inference_request(
        "m" * 256,
        [{"role": "user", "content": "x" * 100000}] * 100,
        [{"type": "function"}],
        True,
        2,
    )
