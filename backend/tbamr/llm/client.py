"""LLM clients. Agents talk to a client through one method, `complete()`.

- ClaudeClient calls the Anthropic Messages API with tool use (live reasoning).
- ReplayClient plays scripted agent policies so the pipeline runs offline. Its output is
  labelled "replay" everywhere, so nobody mistakes it for live reasoning.

Blocks are normalised to plain dicts:
  {"type": "text", "text": "..."}
  {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")


class LLMClient(Protocol):
    mode: str

    def complete(self, agent: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


class ClaudeClient:
    mode = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None, max_tokens: int = 2048):
        import anthropic  # imported lazily so replay mode needs no key

        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, agent, system, messages, tools):
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages, tools=tools
        )
        out: list[dict[str, Any]] = []
        for b in resp.content:
            if b.type == "text":
                out.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)})
        return out

    def text(self, system: str, prompt: str) -> str:
        resp = self.client.messages.create(model=self.model, max_tokens=800, system=system, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text")


Policy = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


class ReplayClient:
    """Deterministic stand-in for Claude. Each agent has a scripted policy (see replay.py)."""

    mode = "replay"

    def __init__(self, policies: dict[str, Policy] | None = None):
        from .replay import POLICIES

        self.policies = policies or POLICIES
        self._n = 0

    def complete(self, agent, system, messages, tools):
        policy = self.policies.get(agent)
        if policy is None:
            raise KeyError(f"No replay policy for agent '{agent}'")
        blocks = policy(messages)
        for b in blocks:
            if b["type"] == "tool_use" and "id" not in b:
                self._n += 1
                b["id"] = f"replay_{self._n}"
        return blocks

    def text(self, system: str, prompt: str) -> str:
        return ("[Replay mode — no live model] This summary is generated from the report numbers by a template. "
                "Add an Anthropic API key to have Claude draft it.")


def make_client(mode: str | None = None) -> LLMClient:
    mode = (mode or os.environ.get("TBAMR_BRAIN") or ("claude" if os.environ.get("ANTHROPIC_API_KEY") else "replay")).lower()
    return ClaudeClient() if mode == "claude" else ReplayClient()
