# Oracle Arc Project Two deployment runbook

This is the deployment contract for the current SQLite-backed control plane and separate worker process. It is a runbook, not a claim that a production environment has already been provisioned.

## Required topology

Run the API and the worker on the same Linux host (or on processes with the same reliable local persistent filesystem). Both must use the same `ORACLE_ARC_DB_PATH`. The older customer-facing `/v1/tenants` identity API must use a separate `ORACLE_ARC_TENANT_IDENTITY_DB_PATH`.

Do not mount the SQLite database over NFS/object storage, and do not run API/worker replicas on different hosts against a shared SQLite file. The current implementation is not a distributed database or multi-host lease service. For horizontal scaling, migrate the control-plane stores and lease/event transactions to a managed PostgreSQL database before adding replicas.

## API process

Install the pinned Python dependencies from `requirements-core.txt`, set server-side environment variables, then run:

```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Place the API behind a TLS reverse proxy. Expose only the required public API routes; do not expose the owner key or database file. Configure `ORACLE_ARC_API_KEY` with a long random secret and exact CORS origins only if browser-direct API access is required. Prefer the same-origin Project One BFF for owner operations.

## Worker process

Run a separate worker process as a dedicated unprivileged Linux user with rootless Podman installed and configured. Build the calculator worker image with `sh scripts/build-plugin-worker.sh` and verify the resulting image ID before issuing worker credentials. The image runs `core/plugin_worker.py` as UID/GID 65534 with no network, read-only root filesystem, no Linux capabilities, no-new-privileges, CPU/memory/PID/file limits and bounded arithmetic. Do not grant the API process access to the Podman socket.

Set:
- `ORACLE_ARC_DB_PATH`: exactly the same local database path used by the API.
- `ORACLE_ARC_WORKER_TOKEN`: short-lived worker credential issued by the owner API, scoped to one tenant/application, with only the execution lifecycle capabilities required and `tool.calculate` only when calculator access is intended.
- `ORACLE_ARC_PLUGIN_WORKER_IMAGE`: the reviewed, pinned plugin-worker image tag.
- `OLLAMA_HOST` or the relevant remote provider API key/model environment variables.

Run:

```bash
python -m core.platform_worker
```

The worker is the only process that should invoke Podman. Keep its Linux user, rootless container storage, image allowlist and network egress constrained. Do not pass owner API credentials to the worker.

## Data and model egress policy

- Keep `ORACLE_ARC_DB_PATH` and `ORACLE_ARC_TENANT_IDENTITY_DB_PATH` separate.
- Use a persistent local disk with restrictive filesystem permissions and scheduled, tested SQLite backups.
- Ollama is the local route for private data.
- OpenRouter, Groq, Gemini and Claude routes are restricted to public-classified data until a provider-specific data-processing, residency and egress policy is approved.
- Do not interpret the execution `region` label as a guarantee of the remote provider's physical processing region.

## Project One owner BFF

The Netlify Function in Project One needs server-only values for the Project Two API origin and owner API key, plus the trusted identity provider's owner-session signing secret, issuer and exact Project One origin allowlist. The identity provider must issue the short-lived owner JWT and double-submit CSRF cookie documented in Project One's `docs/OWNER_BFF_CONTRACT.md`.

## Go-live checks

1. Provision a fresh environment and separate database paths.
2. Create the tenant/application and issue least-privilege application and worker credentials.
3. Configure a local Ollama route and a bounded quota.
4. Grant only the tools required by the agent.
5. Register a versioned agent manifest and run a calculator smoke execution.
6. Verify owner revocation blocks subsequent calls and waits for any already-authorized bounded tool invocation to finish.
7. Verify SSE event replay, credential expiry, cancellation, worker restart and expired-lease recovery.
8. Verify the API is reachable only through TLS and the worker cannot be reached from the public network.
9. Restore a backup in a separate test environment before production traffic.

No Project Two production host, persistent volume or worker credential was available in the connected environment during this implementation. Do not mark production deployment complete until the runbook is executed against a real host and the go-live checks pass.
