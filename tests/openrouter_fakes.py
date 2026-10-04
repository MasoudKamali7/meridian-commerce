"""
Offline test doubles for the OpenAI SDK surface that OpenRouterLLMClient uses.

Nothing here touches the network or needs a real key: `install_fake_openai`
swaps the `OpenAI` class that src.ai.llm_client imported for `FakeOpenAI`,
and real `openai` exception classes are constructed exactly the way the SDK
raises them (with an httpx request/response attached).
"""

import json
from types import SimpleNamespace

import httpx
import openai

TEST_KEY = "test-key-not-real-0000"   # obviously fake; never a real credential
_URL = "https://openrouter.ai/api/v1/chat/completions"


def _request():
    return httpx.Request("POST", _URL)


def status_error(cls, status: int, message: str = "error"):
    return cls(message, response=httpx.Response(status, request=_request()), body=None)


def auth_error(message="Invalid API key"):
    return status_error(openai.AuthenticationError, 401, message)


def rate_limit_error(message="Rate limit exceeded: free-models-per-min"):
    return status_error(openai.RateLimitError, 429, message)


def server_error(message="Upstream provider error"):
    return status_error(openai.InternalServerError, 500, message)


def bad_request_error(message="Provider returned error"):
    return status_error(openai.BadRequestError, 400, message)


def payment_required_error(message="Insufficient credits"):
    return status_error(openai.APIStatusError, 402, message)


def timeout_error():
    return openai.APITimeoutError(request=_request())


def connection_error():
    return openai.APIConnectionError(message="Connection error.", request=_request())


def tool_call_response(tool_name: str, arguments, prompt_tokens=120, completion_tokens=45,
                       finish_reason="tool_calls", model="some-provider/some-model:free"):
    """A chat.completions response carrying one function tool call."""
    if not isinstance(arguments, (str, dict)) and arguments is not None:
        arguments = json.dumps(arguments)
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    call = SimpleNamespace(id="call_1", type="function",
                           function=SimpleNamespace(name=tool_name, arguments=arguments))
    message = SimpleNamespace(role="assistant", content=None, tool_calls=[call])
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        model=model,
    )


def text_only_response(text="Sure! Here is the answer."):
    message = SimpleNamespace(role="assistant", content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(index=0, message=message, finish_reason="stop")],
                           usage=None, model="x:free")


class _Completions:
    def __init__(self, owner):
        self._owner = owner

    def create(self, **kwargs):
        self._owner.calls.append(kwargs)
        if not self._owner.outcomes:
            raise AssertionError("FakeOpenAI: no more programmed outcomes")
        outcome = self._owner.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeOpenAI:
    """Records constructor kwargs and every chat.completions.create call."""
    instances = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.calls = []
        self.outcomes = list(FakeOpenAI._next_outcomes)
        self.chat = SimpleNamespace(completions=_Completions(self))
        FakeOpenAI.instances.append(self)

    _next_outcomes = []


def install_fake_openai(monkeypatch, outcomes):
    """Patch the SDK class used by llm_client and neutralize retry sleeps.
    Returns a callable giving the most recently constructed FakeOpenAI."""
    import src.ai.llm_client as llm_client_module
    FakeOpenAI.instances = []
    FakeOpenAI._next_outcomes = list(outcomes)
    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.time, "sleep", lambda s: None)
    return lambda: FakeOpenAI.instances[-1]
