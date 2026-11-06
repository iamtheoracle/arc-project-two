"""Run the Oracle Arc API:  python -m oracle_arc  (env: ARC_SERVER_KEY, ARC_APP_ID/ARC_APP_SECRET, ARC_PORT)"""
import os
import sys

from .gateway import Arc, default_backends
from .models import RoutingPolicy
from .types import DataClass


def main() -> int:
    key = os.environ.get("ARC_SERVER_KEY")
    if not key or len(key) < 32:
        print("ARC_SERVER_KEY (>= 32 chars) is required so tokens survive restarts and cannot be forged.", file=sys.stderr)
        return 2
    allow_remote = os.environ.get("ARC_ALLOW_REMOTE") == "1"
    ceiling = DataClass[os.environ.get("ARC_REMOTE_MAX_DATA_CLASS", "PUBLIC")]
    arc = Arc(default_backends(), server_key=key.encode(), audit_path=os.environ.get("ARC_AUDIT_DB", "arc_audit.db"),
              memory_path=os.environ.get("ARC_MEMORY_DB", "arc_memory.db"),
              policy=RoutingPolicy(allow_remote=allow_remote, remote_max_data_class=ceiling))
    app_id, secret = os.environ.get("ARC_APP_ID"), os.environ.get("ARC_APP_SECRET")
    if app_id and secret:
        arc.apps.register_app(app_id, secret, scopes=("chat",))
    host, port = os.environ.get("ARC_HOST", "127.0.0.1"), int(os.environ.get("ARC_PORT", "8787"))
    print(f"Oracle Arc listening on http://{host}:{port}  (remote inference: {'on' if allow_remote else 'off'})")
    arc.make_server(host, port).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
