"""Run Oracle Arc trusted worker workloads.

Start with ORACLE_ARC_WORKER_TOKEN and ORACLE_ARC_DB_PATH configured in the
worker's secret/environment. This runner executes only platform-installed
runtime handlers; it does not load developer-provided Python packages or code.
"""
from __future__ import annotations

import os
import signal
import threading
import time

from core.platform_control_plane import PlatformControlPlane
from core.platform_runtime import RuntimeUnavailable, default_runtime_registry
from core.platform_workers import WorkerService


def run_once(workers: WorkerService, worker, runtimes, lease_seconds: int = 900) -> bool:
    execution = workers.claim(worker, lease_seconds=lease_seconds)
    if execution is None:
        return False

    lost_lease = threading.Event()
    stop_heartbeat = threading.Event()

    def keep_lease_alive():
        while not stop_heartbeat.wait(60):
            try:
                if not workers.heartbeat(worker, execution["execution_id"], lease_seconds):
                    lost_lease.set()
                    return
            except Exception:
                lost_lease.set()
                return

    heartbeat = threading.Thread(target=keep_lease_alive, name="arc-worker-heartbeat", daemon=True)
    heartbeat.start()
    try:
        manifest = workers.execution_manifest(worker, execution["execution_id"])
        result = runtimes.execute(manifest["runtime"], execution, manifest)
        if lost_lease.is_set():
            return True
        for metric in ("input_tokens", "output_tokens"):
            quantity = result.get(metric)
            if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 0:
                workers.record_usage(worker, execution["execution_id"],
                                     f"attempt-{execution['attempt']}-{metric}",
                                     metric, quantity)
        workers.complete(worker, execution["execution_id"], result)
    except RuntimeUnavailable:
        workers.fail(worker, execution["execution_id"], "runtime_unavailable", retryable=False)
    except (ValueError, PermissionError):
        workers.fail(worker, execution["execution_id"], "invalid_or_unauthorized_work", retryable=False)
    except Exception:
        workers.fail(worker, execution["execution_id"], "provider_or_runtime_error", retryable=True)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=2)
    return True


def main() -> None:
    token = os.environ.get("ORACLE_ARC_WORKER_TOKEN", "").strip()
    database = os.environ.get("ORACLE_ARC_DB_PATH", "data/oracle_arc.sqlite3")
    poll_seconds = float(os.environ.get("ORACLE_ARC_WORKER_POLL_SECONDS", "1"))
    if not token:
        raise RuntimeError("ORACLE_ARC_WORKER_TOKEN must be configured")
    if not 0.1 <= poll_seconds <= 30:
        raise RuntimeError("ORACLE_ARC_WORKER_POLL_SECONDS must be between 0.1 and 30 seconds")

    workers = WorkerService(database)
    worker = workers.authenticate(token)
    runtimes = default_runtime_registry()
    control_plane = PlatformControlPlane(database)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    last_recovery = 0.0

    while not stopped.is_set():
        now = time.monotonic()
        if now - last_recovery >= 30:
            control_plane.recover_expired_leases()
            last_recovery = now
        try:
            processed = run_once(workers, worker, runtimes)
        except PermissionError:
            # Revoked/expired worker credentials terminate the process; do not retry.
            raise
        if not processed:
            stopped.wait(poll_seconds)


if __name__ == "__main__":
    main()
