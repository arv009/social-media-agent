"""Keeps the agent's connectors running in the background for the Streamlit app.

Streamlit reruns the page script on every click, but the connectors are long-running processes.
So they live on a background thread with its own event loop, shared by all reruns. When an account
is connected or disconnected, the runtime restarts so the agent picks up the new connectors.
"""
import asyncio
import threading

from social_agent.agent import ConnectorHub, MarketingAgent

_lock = threading.Lock()
_runtimes: dict[str, "AgentRuntime"] = {}


class AgentRuntime:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="agent-runtime")
        self.thread.start()
        self.hub: ConnectorHub | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._life = asyncio.run_coroutine_threadsafe(self._lifecycle(), self.loop)
        self._ready.wait(timeout=120)
        if self._life.done():  # startup failed
            self._life.result()

    async def _lifecycle(self):
        # Opening and closing the connectors must happen in the same task, so this task holds them open.
        self._stop = asyncio.Event()
        async with ConnectorHub() as hub:
            self.hub = hub
            self._ready.set()
            await self._stop.wait()

    def run(self, coro, timeout: float = 600):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def ask(self, messages: list, text: str, on_event) -> tuple[str, str, list]:
        """Run one agent request. Returns (answer, model that answered, updated messages)."""
        agent = MarketingAgent(self.hub, on_event=on_event)
        agent.messages = messages
        answer = self.run(agent.ask(text))
        return answer, agent.last_model, agent.messages

    def close(self):
        if self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
            try:
                self._life.result(timeout=20)
            except Exception:  # noqa: BLE001 - shutting down anyway
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def get_runtime(version: str) -> AgentRuntime:
    """One runtime per connection state; older ones are shut down."""
    with _lock:
        if version not in _runtimes:
            for old in list(_runtimes):
                _runtimes.pop(old).close()
            _runtimes[version] = AgentRuntime()
        return _runtimes[version]
