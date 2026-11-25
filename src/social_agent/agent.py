"""The marketing agent: Claude + your connectors (MCP servers), the same idea as Claude's connectors.

    async with ConnectorHub() as hub:
        agent = MarketingAgent(hub)
        print(await agent.ask("Write a LinkedIn post about our December webinar"))

ConnectorHub starts every enabled connector listed in connectors/connectors.json
whose requirements are met (env vars / files), and collects their tools.
MarketingAgent runs the tool-use loop with Claude.
"""
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "connectors" / "connectors.json"
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # so CLAUDE_MODEL in .env is read before MODEL is set

# Which Claude model the agent uses. Change it in .env with CLAUDE_MODEL, e.g.
#   claude-haiku-5-5  (default: fastest, cheapest)
#   claude-sonnet-5-5 (more careful)   claude-opus-5-5 (most capable)
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

# Models that support the API's server-side refusal fallback. Haiku doesn't, so it's skipped there.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-opus-5"}

# If a model declines a request, the agent retries the same step with the next model in this list,
# finishes the request there, then goes back to its usual model for the next request.
ESCALATION = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
MODEL_NAMES = {"claude-haiku-5-5": "Haiku 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-opus-5-5": "Opus 5.5"}


def model_name(model: str) -> str:
    return MODEL_NAMES.get(model, model)


def escalation_chain(base: str) -> list[str]:
    """The base model, then every stronger model after it, e.g. haiku -> sonnet -> opus."""
    if base in ESCALATION:
        return ESCALATION[ESCALATION.index(base):]
    return [base] + [m for m in ESCALATION[1:] if m != base]

SYSTEM_PROMPT = """You are a social media marketing agent for a small business. You have connectors \
(tools) for analytics, a human review queue, and some social platforms.

How to write a post:
1. Call content_insights (and top_posts if useful) to see what has worked for this account.
2. Write 3 clearly different variants for the requested platform.
3. Call score_drafts with all variants (use media_type "image" if you will make a graphic), then \
best_posting_times for the winner.
4. Make the image: if the canva connector is available and has brand templates, use create_from_template; \
otherwise use make_post_graphic. If canva is available, send_image_to_canva so the reviewer can polish it.
5. Submit the best variant with submit_post_draft, including image_url (the image path, or the public image \
URL for Instagram), design_link (Canva edit link, if any), the predicted engagement, suggested time, \
and a one-line agent_notes explaining why it won. Then tell the user the draft number and summarize the \
other variants briefly. Follow the brand voice from brand_guidelines.

How to handle comments: read them with list_comments, write a short, friendly, on-brand reply, and save it \
with submit_reply_draft. Never promise discounts, prices, refunds or anything legal; for complaints, \
apologize and invite the person to send a direct message.

Rules:
- Only a human can approve drafts. Never say something was posted or scheduled unless a publishing tool \
returned success.
- If a draft was rejected, read the reviewer_note with get_draft and use revise_draft.
- If a tool you need is not available, say which connector is missing instead of pretending.
- If performance_summary shows the data source is "sample", mention that results come from sample data.
- Keep replies to the user short and practical."""


@dataclass
class ConnectorStatus:
    name: str
    description: str
    state: str          # connected | needs_setup | disabled | planned | error
    detail: str = ""
    tools: list[str] = field(default_factory=list)


class ConnectorHub:
    """Starts connector servers and routes tool calls to the right one."""

    def __init__(self, registry_path: Path = REGISTRY, only: list[str] | None = None):
        self.registry = json.loads(Path(registry_path).read_text())
        self.only = only
        self.status: list[ConnectorStatus] = []
        self.tools: list[dict] = []                 # Claude tool definitions
        self._route: dict[str, ClientSession] = {}  # tool name -> server session
        self._stack = AsyncExitStack()

    def _check(self, cfg: dict) -> str:
        missing_env = [v for v in cfg.get("requires_env", []) if not os.getenv(v)]
        missing_files = [f for f in cfg.get("requires_files", []) if not (ROOT / f).exists()]
        parts = []
        if missing_env:
            parts.append(f"set {', '.join(missing_env)} in .env")
        if missing_files:
            parts.append(f"missing {', '.join(missing_files)}")
        return "; ".join(parts)

    async def __aenter__(self):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        for name, cfg in self.registry.items():
            desc = cfg.get("description", "")
            if self.only and name not in self.only:
                continue
            if cfg.get("status") == "planned":
                self.status.append(ConnectorStatus(name, desc, "planned", cfg.get("notes", "")))
                continue
            if not cfg.get("enabled", True):
                self.status.append(ConnectorStatus(name, desc, "disabled"))
                continue
            problem = self._check(cfg)
            if problem:
                self.status.append(ConnectorStatus(name, desc, "needs_setup", problem))
                continue
            try:
                # env: pass our environment through (by default MCP only passes a few safe variables)
                params = StdioServerParameters(command=sys.executable, args=[str(ROOT / cfg["script"])],
                                               cwd=ROOT, env=dict(os.environ))
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = (await session.list_tools()).tools
            except Exception as e:  # noqa: BLE001 - one broken connector shouldn't stop the others
                self.status.append(ConnectorStatus(name, desc, "error", str(e)))
                continue
            for tool in listed:
                if tool.name in self._route:
                    raise ValueError(f"Two connectors define a tool named {tool.name!r}")
                self._route[tool.name] = session
                self.tools.append({"name": tool.name, "description": tool.description or "",
                                   "input_schema": tool.input_schema})
            self.status.append(ConnectorStatus(name, desc, "connected", tools=[t.name for t in listed]))
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Run a tool on its connector. Returns (text, is_error)."""
        session = self._route.get(name)
        if session is None:
            return f"Unknown tool {name}", True
        result = await session.call_tool(name, arguments)
        text = "\n".join(c.text for c in getattr(result, "content", []) if getattr(c, "type", "") == "text")
        return text or "(no output)", bool(getattr(result, "is_error", False))

    def status_table(self) -> str:
        icons = {"connected": "✅", "needs_setup": "⚙️ ", "disabled": "⏸ ", "planned": "🗓 ", "error": "❌"}
        lines = []
        for s in self.status:
            extra = f"{len(s.tools)} tools" if s.state == "connected" else s.detail
            lines.append(f"{icons[s.state]} {s.name:<13} {s.state:<12} {extra}")
        return "\n".join(lines)


class MarketingAgent:
    """A tool-use loop: Claude decides which connector tools to call until the task is done."""

    def __init__(self, hub: ConnectorHub, model: str = MODEL, effort: str = "medium", on_event=None):
        self.hub = hub
        self.model = model            # the usual model; /model in agent_chat.py changes it
        self.last_model = model       # the model that produced the last answer
        self.effort = effort
        self.client = anthropic.AsyncAnthropic()
        self.messages: list = []
        self.on_event = on_event or (lambda kind, data: None)  # e.g. print tool calls as they happen

    async def _create(self, model: str):
        extra = {}
        if model in FALLBACK_MODELS:
            # If the model declines for safety reasons, the API retries on a fallback model.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        return await self.client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.hub.tools,
            messages=self.messages,
            output_config={"effort": self.effort},
            **extra,
        )

    async def ask(self, user_text: str, max_steps: int = 25) -> str:
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        # Every request starts on the usual model. If it declines, step up the chain
        # (Haiku -> Sonnet -> Opus) and stay there until this request is finished.
        chain = escalation_chain(self.model)
        level = 0
        for _ in range(max_steps):
            model = chain[level]
            self.last_model = model
            response = await self._create(model)

            if response.stop_reason == "refusal":
                # The declined reply is not added to the conversation; the next model gets the same step.
                if level + 1 < len(chain):
                    level += 1
                    self.on_event("model_switch", {"from": model, "to": chain[level]})
                    continue
                # Every model declined: drop this request from the conversation so it doesn't affect the next one.
                del self.messages[start:]
                tried = ", ".join(model_name(m) for m in chain)
                return f"The model declined this request (tried {tried}). Try rephrasing it."

            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "max_tokens" and not tool_calls:
                return _text(response) + "\n\n[response was cut off]"
            if not tool_calls:
                return _text(response)

            results = []
            for call in tool_calls:
                self.on_event("tool_call", {"name": call.name, "input": call.input})
                try:
                    text, is_error = await self.hub.call(call.name, call.input)
                except Exception as e:  # noqa: BLE001 - report the failure to the model
                    text, is_error = f"Error: {e}", True
                self.on_event("tool_result", {"name": call.name, "text": text, "is_error": is_error})
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": text,
                                **({"is_error": True} if is_error else {})})
            self.messages.append({"role": "user", "content": results})
        return "Stopped: too many steps without finishing."


def _text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()
