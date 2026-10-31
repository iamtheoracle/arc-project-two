"""Independent Oracle Arc agent worker.

Run with: python -m core.agent_worker
Workers share the configured durable database and use task leases for exclusive claims.
"""
from __future__ import annotations

import os
import signal
import threading
import time
import uuid
from typing import Any

from core.store import ArcStore

LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
POLL_SECONDS = 2


def process_one(store: ArcStore, worker_id: str) -> bool:
    store.recover_expired_agent_tasks(max_attempts=5)
    task = store.claim_agent_task(worker_id, lease_seconds=LEASE_SECONDS)
    if task is None:
        return False
    stop = threading.Event()
    lease_lost = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                if not store.renew_agent_task_lease(task["task_id"], worker_id, LEASE_SECONDS):
                    lease_lost.set()
                    return
            except Exception:
                lease_lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        payload = task["payload"]
        required = ("model", "history", "latest_user", "max_steps")
        if any(key not in payload for key in required):
            raise ValueError("Task payload is incomplete")
        # Import application wiring only in the worker process, never from a manifest.
        from api import _build_agent_registry, _model_name
        payload["model"] = _model_name(payload["model"])
        if not isinstance(payload["latest_user"], str) or not payload["latest_user"].strip():
            raise ValueError("Task user message is invalid")
        if not isinstance(payload["history"], list) or len(payload["history"]) > 79:
            raise ValueError("Task history is invalid")
        if not isinstance(payload["max_steps"], int) or not 1 <= payload["max_steps"] <= 8:
            raise ValueError("Task step limit is invalid")
        for message in payload["history"]:
            if (not isinstance(message, dict)
                or message.get("role") not in ("user", "assistant")
                or not isinstance(message.get("content"), str)
                or len(message["content"]) > 100_000):
                raise ValueError("Task history entry is invalid")
        registry = _build_agent_registry(store)
        result = registry.dispatch(
            task["target_agent"], payload,
            required_capabilities=tuple(task["required_capabilities"]),
        )
        if lease_lost.is_set():
            return True
        store.update_agent_task(
            task["task_id"], "succeeded",
            connector_id=result["connector_id"], provider=result["provider"],
            worker_id=worker_id, result={"answer": result["result"]},
        )
    except Exception as exc:
        if not lease_lost.is_set():
            try:
                store.update_agent_task(
                    task["task_id"], "failed",
                    error_code="worker_" + type(exc).__name__.lower()[:48],
                    worker_id=worker_id,
                )
            except Exception:
                pass
    finally:
        stop.set()
        thread.join(timeout=2)
    return True


def run_forever() -> None:
    worker_id = os.environ.get("ORACLE_ARC_WORKER_ID", "").strip() or "arc-worker-" + uuid.uuid4().hex
    store = ArcStore()
    shutdown = threading.Event()

    def stop(_signum, _frame) -> None:
        shutdown.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not shutdown.is_set():
        try:
            worked = process_one(store, worker_id)
        except Exception:
            worked = False
        if not worked:
            shutdown.wait(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
