"""Checks the Claude client builds valid Messages API requests, using a fake SDK object (no network, no key)."""
from types import SimpleNamespace as NS

from tbamr.agents.scope_guardian import ScopeGuardian
from tbamr.core.decisions import DecisionLog
from tbamr.llm.client import ClaudeClient


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return NS(content=[NS(type="text", text="Checking the scope."), NS(type="tool_use", id="tu_1", name="submit",
                     input={"blocking": [], "gaps": [], "warnings": ["w"], "asks_comparison_across_places": True})])
        raise AssertionError("should have stopped after submit")


def test_claude_client_request_shape(monkeypatch):
    c = ClaudeClient.__new__(ClaudeClient)
    c.model, c.max_tokens = "claude-test", 512
    c.client = NS(messages=FakeMessages())
    res = ScopeGuardian(DecisionLog(), c).review("Compare regions?", "Indonesia", ["Rifampicin"], 8)
    kw = c.client.messages.calls[0]
    assert kw["model"] == "claude-test" and kw["tools"][-1]["name"] == "submit"
    assert all({"name", "description", "input_schema"} <= set(t) for t in kw["tools"])
    assert kw["messages"][0]["role"] == "user" and "Context (JSON)" in kw["messages"][0]["content"]
    assert res["asks_comparison_across_places"] is True and len(res["gaps"]) == 4
