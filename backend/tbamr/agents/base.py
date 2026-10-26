"""Agent base classes.

RuleAgent  — deterministic: same input, same decisions (QC, profiling, report math).
LLMAgent   — Claude-powered: given a goal and tools, it decides which tools to call and when
             to stop, then submits a structured result. Its submission is checked by
             guardrails before anything reaches the pipeline state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..core.decisions import Decision, DecisionLog, Outcome


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    fn: Callable[..., Any]

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


GUARDRAILS_TEXT = (
    "Non-negotiable rules: use only the five outcomes Proceed, Hold, Exclude, Retry, Escalate. "
    "Never invent accessions, numbers or publications; use only what your tools return. "
    "Never relax a mandatory criterion to reach a sample count. Never upgrade an uncertain finding to confirmed. "
    "Never make clinical or prevalence claims. When evidence is ambiguous, escalate to a human with the evidence you found. "
    "Finish by calling the submit tool exactly once."
)


class BaseAgent:
    name = "agent"
    title = "Agent"
    kind = "rule"
    description = ""

    def __init__(self, log: DecisionLog):
        self.log = log

    def decide(self, sample_id: str, outcome: Outcome, rule: str, rationale: str, evidence: str = "", stage: int = 0) -> Decision:
        return self.log.add(Decision(sample_id=sample_id, outcome=outcome, rule_version=rule, rationale=rationale,
                                     actor=f"agent:{self.name}", evidence=evidence, stage=stage))

    def card(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "kind": self.kind, "description": self.description,
                "tools": [t.name for t in getattr(self, "tools", [])]}


class RuleAgent(BaseAgent):
    kind = "rule"


class LLMAgent(BaseAgent):
    kind = "llm"
    system_prompt = ""
    max_steps = 8
    submit_schema: dict[str, Any] = {"type": "object", "properties": {}}
    submit_description = "Submit your final result."

    def __init__(self, log: DecisionLog, client):
        super().__init__(log)
        self.client = client
        self.tools: list[Tool] = self.build_tools()

    # to override --------------------------------------------------------------
    def build_tools(self) -> list[Tool]:
        return []

    def validate(self, submission: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return submission

    # loop -------------------------------------------------------------------------
    def run(self, task: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = ctx or {}
        self.called: dict[str, list[Any]] = {}
        system = f"You are the {self.title} in a TB genomic drug-resistance research workflow (A.G.E.N.T. Playbook). {self.system_prompt}\n\n{GUARDRAILS_TEXT}"
        tools = [t.spec() for t in self.tools] + [{"name": "submit", "description": self.submit_description, "input_schema": self.submit_schema}]
        messages: list[dict[str, Any]] = [{"role": "user", "content": task + ("\n\nContext (JSON):\n" + json.dumps(ctx, default=str) if ctx else "")}]
        self.log.trace(self.name, "task", {"task": task, "mode": self.client.mode})
        by_name = {t.name: t for t in self.tools}
        for step in range(self.max_steps):
            blocks = self.client.complete(self.name, system, messages, tools)
            for b in blocks:
                if b["type"] == "text" and b["text"].strip():
                    self.log.trace(self.name, "thought", {"text": b["text"], "mode": self.client.mode})
            uses = [b for b in blocks if b["type"] == "tool_use"]
            if not uses:
                self.log.trace(self.name, "stopped", {"reason": "no tool call or submission", "step": step})
                break
            results = []
            for u in uses:
                if u["name"] == "submit":
                    try:
                        accepted = self.validate(u["input"], ctx)
                    except Exception as e:  # malformed submission → escalate, never crash the pipeline
                        self.log.trace(self.name, "guardrail", {"rejected": str(e)})
                        return {"ok": False, "error": str(e), "submission": u["input"]}
                    self.log.trace(self.name, "submit", accepted)
                    return {"ok": True, **accepted}
                tool = by_name.get(u["name"])
                if tool is None:
                    out: Any = {"error": f"Unknown tool {u['name']}"}
                else:
                    try:
                        out = tool.fn(**u["input"])
                    except Exception as e:  # tool failures are data for the agent, not crashes
                        out = {"error": f"{type(e).__name__}: {e}"}
                self.called.setdefault(u["name"], []).append(out)
                self.log.trace(self.name, "tool_call", {"tool": u["name"], "input": u["input"], "output_preview": _preview(out)})
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(out, default=str)[:60000]})
            messages.append({"role": "assistant", "content": [b for b in blocks if b["type"] != "text" or b["text"].strip()]})
            messages.append({"role": "user", "content": results})
        return {"ok": False, "error": "Agent stopped without submitting a result."}


def _preview(out: Any) -> Any:
    if isinstance(out, dict):
        p = {k: v for k, v in out.items() if k != "runs"}
        if "runs" in out:
            p["runs"] = f"{len(out['runs'])} runs"
        return p
    if isinstance(out, list):
        return f"{len(out)} items" if len(out) > 3 else out
    return out
