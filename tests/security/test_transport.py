import asyncio

import pytest

from opsboard import security


def request(messages, headers=(), query=b"", path="/health"):
    sent = []
    calls = []
    queue = iter(messages)

    async def app(scope, receive, send):
        calls.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return next(queue)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": query,
        "client": ("127.0.0.1", 12345),
    }
    asyncio.run(
        security.SecurityMiddleware(app, security.RequestLimiter())(
            scope, receive, send
        )
    )
    return sent[0]["status"], calls


def test_chunked_body_is_bounded():
    status, calls = request(
        [
            {"type": "http.request", "body": b"x" * 10000, "more_body": True},
            {"type": "http.request", "body": b"x" * 10000, "more_body": False},
        ]
    )
    assert (status, calls) == (413, [])


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"0"), (b"content-length", b"0")],
        [(b"content-length", b"0"), (b"transfer-encoding", b"chunked")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"2")],
    ],
)
def test_ambiguous_or_incorrect_framing_is_rejected(headers):
    assert request([{"type": "http.request", "body": b""}], headers)[0] == 400


def test_absolute_body_deadline_cannot_be_bypassed_by_immediate_chunks(monkeypatch):
    monkeypatch.setattr(security, "BODY_TIMEOUT_SECONDS", -1)
    assert request([{"type": "http.request", "body": b""}])[0] == 408


def test_query_length_is_bounded():
    assert request([], query=b"x" * 5000)[0] == 414


def test_header_bytes_are_bounded():
    assert request([], headers=[(b"x-extra", b"x" * 20000)])[0] == 431


def test_path_length_is_bounded():
    assert request([], path="/" + "x" * 5000)[0] == 414


def test_rate_limiter_does_not_allocate_unbounded_keys():
    limiter = security.RequestLimiter()
    for index in range(security.MAX_RATE_KEYS):
        assert limiter.allow(str(index), 1)[0]
    assert not limiter.allow("one-too-many", 1)[0]
    assert len(limiter._windows) == security.MAX_RATE_KEYS
