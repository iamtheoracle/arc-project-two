#!/usr/bin/env bash
set -euo pipefail

host="\${OLLAMA_HOST:-http://127.0.0.1:11434}"
model="\${ORACLE_ARC_MODEL:-qwen2.5:7b}"

case "$host" in
  http://localhost|http://localhost:*|http://127.0.0.1|http://127.0.0.1:*|http://\[::1\]|http://\[::1\]:*)
    ;;
  *)
    echo "Refusing non-loopback Ollama host: $host" >&2
    echo "This verification script intentionally tests local inference only." >&2
    exit 2
    ;;
esac

command -v ollama >/dev/null 2>&1 || {
  echo "Ollama CLI is not installed on this host." >&2
  exit 2
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required for the local API check." >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to validate the model response." >&2
  exit 2
}

echo "Pulling model: $model"
ollama pull "$model"
ollama show "$model" >/dev/null

payload="$(python3 -c 'import json,sys; print(json.dumps({
    "model": sys.argv[1],
    "messages": [{"role": "user", "content": "Reply with exactly ORACLE_ARC_LOCAL_INFERENCE_OK"}],
    "stream": False
}))' "$model")"

response="$(curl --fail --silent --show-error \
  --connect-timeout 3 --max-time 180 \
  "$host/api/chat" \
  -H "Content-Type: application/json" \
  --data-binary "$payload")"

python3 -c 'import json,sys
data=json.load(sys.stdin)
message=data.get("message") or {}
content=message.get("content")
if not isinstance(content,str) or not content.strip():
    raise SystemExit("Ollama returned no assistant content")
print("Local Ollama inference succeeded.")
print("Model response:", content.strip()[:300])
' <<<"$response"

echo "Verified local model is pulled, addressable and responding: $model"
