"""Chat with the marketing agent in the terminal.

    python scripts/agent_chat.py

Needs Claude API credentials: ANTHROPIC_API_KEY in .env (or `ant auth login`).
Try: "Write a LinkedIn post about our free webinar next Thursday"

Commands:
  /model                     show the current model
  /model claude-sonnet-5-5   change the usual model (keeps the conversation)
If a model declines a request, the agent automatically retries with Sonnet 5.5, then Opus 5.5,
and goes back to the usual model for the next request.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anthropic  # noqa: E402

from social_agent.agent import ESCALATION, ConnectorHub, MarketingAgent, model_name  # noqa: E402


def show(kind, data):
    if kind == "tool_call":
        args = json.dumps(data["input"])
        print(f"  🔧 {data['name']}({args[:120]}{'…' if len(args) > 120 else ''})")
    elif kind == "tool_result" and data["is_error"]:
        print(f"     ⚠️  {data['text'][:200]}")
    elif kind == "model_switch":
        print(f"  ↪ {model_name(data['from'])} declined; continuing with {model_name(data['to'])}")


def model_command(agent: MarketingAgent, arg: str):
    if not arg:
        print(f"Current model: {model_name(agent.model)} ({agent.model})")
        print("Options: " + ", ".join(ESCALATION) + "\n")
        return
    agent.model = arg
    print(f"Switched to {model_name(arg)}. The conversation continues.\n")


async def main():
    async with ConnectorHub() as hub:
        print("Connectors:\n" + hub.status_table() + "\n")
        agent = MarketingAgent(hub, on_event=show)
        print(f"Model: {model_name(agent.model)}. Type a request, /model to switch, or 'quit'.\n")
        while True:
            try:
                user = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user.lower() in ("quit", "exit", "q"):
                break
            if not user:
                continue
            if user.startswith("/model"):
                model_command(agent, user[len("/model"):].strip())
                continue
            try:
                answer = await agent.ask(user)
                print(f"\nagent> {answer}\n")
                if agent.last_model != agent.model:
                    print(f"  (answered by {model_name(agent.last_model)}; back to "
                          f"{model_name(agent.model)} for the next request)\n")
            except anthropic.AuthenticationError:
                print("No valid Claude API key. Add ANTHROPIC_API_KEY to .env (or run `ant auth login`).")
                break
            except anthropic.RateLimitError:
                print("Rate limited. Wait a minute and try again.")
            except anthropic.APIConnectionError:
                print("Network error. Check your internet connection.")
            except anthropic.NotFoundError:
                print(f"Model {agent.model!r} not found. Use /model to pick another.")
            except anthropic.APIStatusError as e:
                print(f"API error {e.status_code}: {e.message}")


if __name__ == "__main__":
    asyncio.run(main())
