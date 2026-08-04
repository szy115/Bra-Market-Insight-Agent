import json
import ssl

from insight_agent import llm as llm_module


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(
            {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
            }
        ).encode("utf-8")


def test_call_openai_compatible_chat_retries_transient_ssl_eof(monkeypatch) -> None:
    attempts = {"count": 0}
    request_bodies: list[dict[str, object]] = []

    monkeypatch.setattr(
        llm_module,
        "read_settings_values",
        lambda: {
            "INSIGHT_LLM_PROVIDER": "openai",
            "INSIGHT_LLM_MODEL": "test-model",
            "INSIGHT_LLM_TIMEOUT": "30",
            "INSIGHT_LLM_TEMPERATURE": "0.2",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://example.test/v1",
        },
    )
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        request_bodies.append(json.loads(request.data.decode("utf-8")))
        if attempts["count"] == 1:
            raise ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
        return FakeResponse()

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)

    result = llm_module.call_openai_compatible_chat(
        [{"role": "user", "content": "hello"}],
        max_tokens=100_000,
    )

    assert attempts["count"] == 2
    assert result["message"]["content"] == "ok"
    assert request_bodies[-1]["max_tokens"] == 100_000
