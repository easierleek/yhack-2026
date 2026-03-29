# ============================================================
#  NEO — Nodal Energy Oracle
#  frontend/ws_server.py  —  WebSocket broadcast server
#
#  Runs an asyncio event loop in a daemon thread.
#  Call start_ws_server() once at startup (before main loop).
#  Call ws_broadcast(state_dict) from any thread to push state
#  to all connected React clients.
# ============================================================

from __future__ import annotations

import asyncio
import json
import math
import threading
from typing import Any

try:
    import websockets
    from websockets.asyncio.server import serve, ServerConnection
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    print("[WS] websockets not installed — web UI disabled. Run: pip install websockets>=12.0")

# ─── Module state ─────────────────────────────────────────────────────────────

_clients: set = set()
_clients_lock = asyncio.Lock.__new__(asyncio.Lock)   # placeholder; real lock created in thread
_loop: asyncio.AbstractEventLoop | None = None

# Last known state — sent to newly connected clients immediately
_last_state: dict[str, Any] = {}
_last_state_lock = threading.Lock()


# ─── JSON serialisation ────────────────────────────────────────────────────────

def _safe_dump(state: dict) -> str:
    """Serialise state to JSON, replacing non-finite floats with null."""
    def _default(obj: Any) -> Any:
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    # Cap infinity values before serialising so the frontend gets a number, not null
    cleaned: dict = {}
    for k, v in state.items():
        if isinstance(v, float) and math.isinf(v):
            cleaned[k] = 99999.0
        elif isinstance(v, float) and math.isnan(v):
            cleaned[k] = 0.0
        elif isinstance(v, tuple):
            cleaned[k] = list(v)
        else:
            cleaned[k] = v

    return json.dumps(cleaned, default=str)


# ─── Async internals (run inside the WS event loop thread) ────────────────────

async def _handler(websocket: "ServerConnection") -> None:
    """Accept a client, send current snapshot, then wait for disconnect."""
    _clients.add(websocket)
    try:
        # Send the current state immediately so the client isn't blank
        with _last_state_lock:
            snapshot = dict(_last_state)
        if snapshot:
            await websocket.send(_safe_dump(snapshot))
        # Keep connection open until client disconnects
        await websocket.wait_closed()
    except Exception:
        pass
    finally:
        _clients.discard(websocket)


async def _broadcast_coro(payload: str) -> None:
    """Coroutine that fans payload out to every connected client."""
    if not _clients:
        return
    targets = set(_clients)   # snapshot to avoid mutating while iterating
    await asyncio.gather(
        *[ws.send(payload) for ws in targets],
        return_exceptions=True,   # swallow individual client errors
    )


async def _serve_forever(host: str, port: int) -> None:
    async with serve(_handler, host, port):
        await asyncio.Future()   # run until cancelled


# ─── Public API ───────────────────────────────────────────────────────────────

def ws_broadcast(state: dict[str, Any]) -> None:
    """
    Thread-safe, non-blocking broadcast.
    Called from update_state() in dashboard.py after every control cycle.
    Drops the frame silently if the event loop is not yet ready.
    """
    if not _WS_AVAILABLE or _loop is None:
        return
    with _last_state_lock:
        _last_state.update(state)
    try:
        payload = _safe_dump(state)
    except Exception:
        return
    asyncio.run_coroutine_threadsafe(_broadcast_coro(payload), _loop)


def start_ws_server(host: str = "localhost", port: int = 8765) -> None:
    """
    Start the WebSocket server in a background daemon thread.
    Call once at application startup, before the main control loop.
    """
    if not _WS_AVAILABLE:
        return

    def _thread_main() -> None:
        global _loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _loop = loop
        try:
            loop.run_until_complete(_serve_forever(host, port))
        except Exception as e:
            print(f"[WS] Server error: {e}")

    t = threading.Thread(target=_thread_main, daemon=True, name="neo-ws-server")
    t.start()
    print(f"[WS] WebSocket server starting on ws://{host}:{port}")
