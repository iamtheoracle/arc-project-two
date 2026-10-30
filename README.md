# THE ORACLE-ARC

**A private, single-owner AI assistant powered by a locally hosted Ollama model.**

Oracle Arc is a standalone project. It is not Vantoris X Money, UNIBUD, The Arc Space, or a My Realm business application.

## Planned specialist agents

The architecture defines four coordinated roles: **BUD** (everyday companion and coordinator), **SPARK** (permissioned memory and continuity), **ORACLE** (reasoning, research and problem-solving), and **ORBITS** (visual understanding and creative workflows). They are intended to use one shared, provider-independent Oracle Arc service with separate identities and least-privilege permissions. This is an architecture direction, not a claim that the multi-agent runtime is already shipped.

## What is implemented

- Local inference through Ollama; default model: `qwen2.5:7b`.
- Owner-only HTTP API using a server-side bearer secret and constant-time token comparison.
- OpenAI-compatible chat endpoint: `POST /v1/chat/completions`.
- Persistent SQLite conversations and owner-managed memories.
- Memory list, save, and permanent-delete endpoints.
- Tool permissions default to denied. The owner must explicitly approve or revoke each installed tool.
- Tool audit history records approvals, revocations, denials, and executions without storing tool arguments.
- API model selection is pinned to the server-configured model; clients cannot trigger arbitrary model pulls.
- Human-understanding policy: Oracle Arc always replies in polished, correct English while adapting vocabulary, sentence length, detail, and examples to the conversation. It never copies a user's grammar or spelling errors.
- Owner-controlled communication profile for explanation detail, tone, and interests, persisted locally in SQLite.
- Personalization uses authorized conversation context and explicitly saved preferences; interests are optional context, not assumptions or mandatory themes.
- Conversation-led adaptation: the model uses the current conversation to form a temporary, revisable read of the user's goal, tone, familiarity, and support needs. It does not turn every remark into a permanent personality rule.
- Owner-controlled personal boundaries can be listed, added, and revoked. Saved profile, memory, and boundary text is treated as untrusted personal context, never as system policy.
- Automated tests for authentication, persistence, memory deletion, permissions, adaptive communication rules, and agent denial behavior.

## Run locally

Requirements: Python 3.11+ and [Ollama](https://ollama.com/).

```bash
# 1. Install and start Ollama using its official instructions.
ollama pull qwen2.5:7b

# 2. Create an isolated Python environment.
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

# 3. Configure a server-only key. Do not commit .env.
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the generated value in ORACLE_ARC_API_KEY in .env.

# 4. Load the environment variables into this shell.
set -a
. ./.env
set +a

# 5. Start the API bound to loopback, not the public internet.
uvicorn api:app --host 127.0.0.1 --port 8090
```

The model must already be available in Ollama. Oracle Arc does not automatically download arbitrary models from API requests.

## API examples

Set `ORACLE_ARC_API_KEY` in the server environment and use the same value only in a trusted client:

```bash
export ORACLE_ARC_API_KEY='your-server-generated-secret'

curl http://127.0.0.1:8090/v1/chat/completions \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello, Oracle Arc."}]}'
```

Set communication preferences (optional; defaults are simple and natural):

\`\`\`bash
curl -X PUT http://127.0.0.1:8090/v1/profile \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"detail_level":"simple","tone":"natural","interests":["football","anime"]}'
\`\`\`

Oracle Arc uses these interests only when they genuinely help the conversation. The model must always use correct English; it adapts the complexity of its explanation, not its grammar or spelling.

Save a memory:

```bash
curl -X POST http://127.0.0.1:8090/v1/memories \
  -H "Authorization: Bearer $ORACLE_ARC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"I prefer clear, direct explanations.","tags":["preferences"]}'
```

Other owner-authenticated routes:

- `GET /v1/profile` — view the communication profile.
- `GET /v1/boundaries` — list active personal boundaries.
- `POST /v1/boundaries` — save a clearly stated or confirmed boundary.
- `DELETE /v1/boundaries/{boundary_id}` — revoke an active boundary while retaining its audit history.
- `PUT /v1/profile` — update `detail_level` (`simple`, `balanced`, `detailed`), `tone` (`natural`, `warm`, `playful`, `professional`), and up to 30 interests.

- `GET /v1/models`
- `GET /v1/conversations`
- `GET /v1/memories`
- `PUT /v1/memories/{memory_id}` — edit a memory
- `DELETE /v1/memories/{memory_id}` — permanent deletion
- `DELETE /v1/conversations/{conversation_id}` — permanently delete a conversation and its messages
- `GET /v1/tools`
- `PUT /v1/tools/{tool_name}/approval` with `{"approved":true}` or `false`
- `GET /v1/audit/tools`

Conversation continuity: the first chat response returns `conversation_id`. Send it on later requests to continue that persisted conversation.

## Security boundaries

- The API refuses protected requests if `ORACLE_ARC_API_KEY` is missing or incorrect.
- Keep `ORACLE_ARC_API_KEY` and the SQLite database on a trusted server. Never use a `VITE_*` or other browser-exposed variable for secrets.
- The API binds to `127.0.0.1` by default in the documented command. For a remote platform integration, use a private network or authenticated gateway with TLS; do not expose this port publicly without that layer.
- No tools are approved initially. Review each plugin before enabling it.
- Plugin code runs with the operating-system permissions of the Oracle Arc process. Tool approval is not a sandbox: run with least-privilege OS permissions and avoid granting access to sensitive files unnecessarily.
- SQLite is local persistent storage, not encrypted-at-rest storage. Protect the host disk and backups.
- This repository's current GitHub visibility is public. Never put private conversations, memories, keys, or real personal data in source control. If source-code confidentiality is required, change repository visibility to private in GitHub settings.

## Verification

Run:

```bash
pytest -q
```

CI runs the same tests on pushes and pull requests. Passing tests validate the mocked API and permission boundaries; they do **not** prove that Ollama is installed, that a model has been downloaded, or that a live model response has been tested on your hardware.

## Status

This is the first implementation pass of the personal core. Real Ollama inference, remote platform integration, production hosting, and hardware performance still require environment setup and live verification.
