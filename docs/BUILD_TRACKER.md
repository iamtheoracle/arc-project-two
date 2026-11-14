# UNIBUD BUILD TRACKER
Last updated: 2026-11-14. Labels: Current = verified in code/tests this session; Planned = agreed, not built; Concept = name only.
Rule: trust code over this file. Re-verify any claim before relying on it.

## 1. Stopped at / Next exact step
- Stopped: audited the Oracle Arc build (arc-project-two) against the Founder Master Statement. No code changed since commit 0fd65b7 there.
- Founder decision (2026-11-14): **unibud-live is abandoned.** It is a reference only; no new feature work lands here. This tracker and `docs/BUILD_PROMPT.md` are the only additions.
- NEXT EXACT STEP (in order, one at a time):
  1. arc-project-two: remove product agents (Bud/Concierge prompts, "unibud" defaults) from `oracle_arc/gateway.py`; hosts register agents/apps via config (A6).
  2. Agent society: fix `unibud-agents` typecheck, add tests, map the 51 agents to Oracle Arc registration (A12).
  3. PostgreSQL storage for Oracle Arc (A8).
- Then: arc-project-one snapshot integration (section 3).

## 2. Repos and verified state
| Repo | Branch / commit | State | Tests |
|---|---|---|---|
| arc-project-two (Oracle Arc, Python, stdlib only) | branch feat/oracle-arc-core (pushed to GitHub; `main` is the OLD plugin CLI and is untouched). Oracle Arc code is first commit 0fd65b7 | Current: identity/tokens, model gateway (Ollama + opt-in remote, fallback, circuit breaker, quotas), ORACLE pipeline (chat + tools), SPARK memory, ORBITS intake class (no HTTP route), 2 agents, tool grants, confirmation, hash-chained audit, HTTP API incl. /v1/complete. Storage: SQLite + in-memory | 93 pass (+10 mutation checks caught). NOT run against real Ollama/remote |
| unibud-live | ABANDONED. main @ e0692ff | Reference only. `src/lib/oracle/arc-llm.ts` calls api.x.ai (grok-4.5) directly; `src/lib/agents/` has 207 lines of agent runtime | not run |
| unibud-agents (51-agent registry, TS) | local only, paused | registry files exist; typecheck FAILS (tsconfig lacks allowImportingTsExtensions, Node types missing, bad "library" collaborator); no tests | not run |
| arc-project-one (finance/FX snapshot, from zip) | working copy only; repo not reachable from this session | Fixed: shell tests drifted from UI (added `initialScreen` prop to App, updated tests); ledger entry; zip delivered | 141 pass under a local vitest-compatible shim (NOT real vitest); tsc clean for domain/server only |

## 3. Fix queue (priority order)
1. Oracle Arc independence: remove UNIBUD-specific agents/prompts from the core (A6).
2. Agents: unbroken typecheck + tests for unibud-agents; map the 51 agents to Oracle Arc registration (A12).
3. Oracle Arc: PostgreSQL storage with migrations/constraints/RLS (A8); persist apps/grants/agents.
4. Oracle Arc: separate CONCIERGE as its own capability and enforce service boundaries (A7); wire ORBITS into the API (A9); full SPARK user controls (A10).
5. Oracle Arc: privileged-operation approval + admin/staff roles + rate limits (A11); external anchoring of the audit chain (A13).
6. Research provenance model (source/publisher/dataset/geography/period/unit/release/retrieval/methodology/revisions) before any ORACLE research feature or the eleven destinations (A14).
7. arc-project-one: recover RiffApp, SouLyncApp, BoardApp from soulync/board snapshots; navigation audit; demo-callout items.
8. arc-project-one: confirm moon-uiux snapshot has nothing unique (finance branch is a superset).
9. Oracle Arc: real OIDC identity (replaces TrustedAppAssertion), real ClamAV, audio/vision/OCR processors, concierge provider adapters, TLS at proxy.
Parked (only if unibud-live is revived): Oracle Arc client for `arc-llm.ts`, no silent fallback to xAI (A1).

## 4. Audit findings
| # | Finding | Severity | Status |
|---|---|---|---|
| A1 | unibud-live Bud uses xAI directly; LLM invoked, not behind an interface | High | Parked: repo abandoned |
| A2 | Legacy arc-project-two `plugins/files.py` reads any path; calculator allows `9**9**9` | High if network-exposed | Open; legacy untouched, documented |
| A3 | Hardcoded admin backdoor seen in uploaded docs (memory note) | High | Not found in oracle_arc code. Re-grep before every merge |
| A4 | arc-project-one CI failed before steps; cause unknown | Medium | Unverified |
| A5 | Built-in malware scanner detects only EICAR | Medium | Documented; use ClamdScanner |
| A6 | Oracle Arc core hardcodes UNIBUD's Bud and Concierge (prompts, default grants, `agent="bud"` default, app id "unibud" in docs) | High | Open |
| A7 | ORACLE, SPARK, ORBITS, CONCIERGE are one in-process object graph; boundaries are logical only | High | Open |
| A8 | Storage is SQLite/in-memory; statement requires PostgreSQL migrations, constraints, RLS, least-privilege roles | High | Open |
| A9 | ORBITS has no HTTP route and no ORACLE integration | Medium | Open |
| A10 | SPARK lacks user list/correct/delete/retention endpoints and a "purpose" dimension | Medium | Open |
| A11 | No admin/staff roles, no dual approval for privileged ops, no rate limiting | High | Open |
| A12 | Agents untouched: Oracle Arc has 2 of 51; unibud-agents fails typecheck, no tests | High | Open |
| A13 | Audit hash chain needs an externally anchored head to resist DB-level rewrite | Medium | Open |
| A14 | No provenance model for statistics; eleven destinations not started | Planned | Open |
| A15 | `TrustedAppAssertion` is a stop-gap and may compete with UNIBUD's identity authority | High | Open |
Checked and clean: no "Ashcombe" references in arc-project-two, arc-project-one, unibud-agents, unibud-live (2026-11-14).

## 5. Important commands
- Oracle Arc tests: `cd arc-project-two && python3 -W error::ResourceWarning -m unittest discover -s tests -t .`
- Oracle Arc run: `ARC_SERVER_KEY=<>=32 chars> ARC_APP_ID=<app> ARC_APP_SECRET=<long> python3 -m oracle_arc`
- unibud-agents typecheck: `cd unibud-agents && tsc --noEmit -p .` (currently fails).
- arc-project-one real checks (run where registry works): `npm ci && npm test && npm run build`.
- Safety: never merge, deploy, or force-push without approval.

## 6. Where to add improvements
- Oracle Arc: new tools in `oracle_arc/tools/` + grants via host config; model providers in `oracle_arc/models/`; media processors via `Orbits.register_processor`.
- arc-project-one: screens under `src/apps/<name>/`, registered in `src/unibud-navigation.ts`, mounted in `src/App.tsx`.

## 7. Statistics (update every session)
| Metric | Value | As of |
|---|---|---|
| Oracle Arc tests passing | 93 / 93 | 2026-11-12 |
| arc-project-one tests passing (shim) | 141 / 141 | 2026-10-29 |
| Open audit findings | 13 open (A2, A4-A15), 1 parked (A1), A3 not found | 2026-11-14 |
| Agents registered in Oracle Arc | 2 of 51 | 2026-11-14 |
| Eleven destinations built | 0 of 11 | 2026-11-14 |

## 8. Blockers and open decisions
- npm registry unreachable in this environment (cannot run real vitest/build/audit).
- Push to arc-project-two and unibud-live now works (verified 2026-11-14). arc-project-one is still not visible to the sandbox.
- Identity provider (Auth0/Entra/Okta/Google/OIDC) undecided; must not create a competing identity authority (A15).
- Terminology: Spark = memory (Founder Master Statement) vs "hidden orchestration" (AGENT_SYSTEM.md). AGENT_SYSTEM.md needs updating.
- MoneyLeads and UNIBUD stay independent products; no implicit Oracle Arc access to their data.
