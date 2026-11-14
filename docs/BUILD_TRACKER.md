# UNIBUD BUILD TRACKER
Last updated: 2026-11-14. Labels: Current = verified in code during this session; Planned = agreed, not built; Concept = name only.
Rule: trust code over notes. Re-verify claims before relying on them.

## 1. Stopped at / Next exact step
- Current: Oracle Arc A6 host-registration implementation is present in `oracle_arc/gateway.py`; the current verified branch HEAD before this tracker-only update is `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4` on `feat/oracle-arc-core`; the full suite was run against this commit.
- Current: `oracle_arc/gateway.py` no longer defines Bud/Concierge prompts, imports Concierge's product-specific tool factory, auto-registers product agents, auto-grants product tools, or defaults `/v1/chat` and `/v1/complete` to Bud.
- Current: `Arc` accepts host-provided `app_credentials`, `agent_specs`, `tool_specs`, and explicit `tool_grants`; invalid grants referencing missing agents/tools are rejected.
- Current: `tests/helpers.py` now supplies the Bud/Concierge-shaped test fixtures as test-host registrations, not gateway defaults. `tests/test_gateway.py` adds host-isolation/configuration tests. `tests/test_http.py` now supplies explicit agents and checks missing-agent rejection.
- Current: Full suite ran against HEAD `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4` in a hosted Python 3.11.2 environment: `Ran 97 tests in 10.112s`, `OK`. `ResourceWarning` messages for unclosed HTTP test sockets were emitted as ignored exceptions; suite exit code was 0. A6 behavior is now test-verified at this commit.
- Planned: NEXT EXACT STEP — locate the authoritative `unibud-agents` source repository or project attachment containing the 51-agent registry, then inspect its package scripts, tsconfig, source and tests before changing it. No repository named `unibud-agents` was present in the accessible `iamtheoracle` repository list; the accessible `iamtheoracle/unibud` tree did not contain an agent registry.
- Planned: Next implementation item is A12: locate the authoritative 51-agent registry, then repair its typecheck, add tests and map only verified definitions.
- Planned: Then implement Oracle Arc PostgreSQL storage and migrations (A8).
- Founder decision: `unibud-live` is abandoned and reference-only; no new feature work there.

## 2. Repositories and verified state
| Repo | Branch / commit | State | Tests |
|---|---|---|---|
| `arc-project-two` | Current: `feat/oracle-arc-core` @ `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4` before this tracker-only update | Current: gateway uses host-supplied app/agent/tool/grant configuration; storage remains SQLite/in-memory and ORBITS storage is in-memory. | Current: 97 tests passed on this commit; ResourceWarning messages from HTTP test sockets remain visible. |
| `unibud-live` | Current: abandoned/reference-only per founder decision | Current: no new feature work authorized. | Current: not run. |
| `unibud-agents` | Current: no repository with this name was found in the accessible owner repository list; no local working copy or project attachment was found | Planned: inspect the authoritative 51-agent registry once its location is supplied or discovered. | Current: not run; no source/package scripts/tsconfig/tests available. |
| `arc-project-one` | Current: previous working-copy snapshot, not part of this task | Current: no changes in this session. | Historical: 141 passed under a local vitest-compatible shim, not real vitest. |

## 3. Fix queue
1. Current: A6 gateway host-registration slice is implemented and the full suite passed 97 tests at HEAD `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4`; ResourceWarning cleanup remains a follow-up.
2. Planned: A12 — repair `unibud-agents` typecheck, add tests, map all 51 agent definitions to Oracle Arc host registration without inventing capabilities.
3. Planned: A8 — PostgreSQL storage, migrations, constraints, RLS, least-privilege roles; persist app/agent/grant configuration.
4. Planned: A7 — separate ORACLE, SPARK, ORBITS and CONCIERGE service boundaries.
5. Planned: A9 — ORBITS API route and governed ORACLE integration.
6. Planned: A10 — SPARK user list/correct/delete/retention endpoints and purpose dimension.
7. Planned: A11 — admin/staff roles, dual approval and rate limits.
8. Planned: A13 — externally anchored audit-chain head.
9. Planned: A14 — research provenance model before ORACLE statistics/research destinations.
10. Planned: A15 — replace `TrustedAppAssertion` with an identity-provider integration chosen by the founder.

## 4. Audit findings
| # | Finding | Severity | Status |
|---|---|---|---|
| A1 | `unibud-live` Bud uses a direct model provider | High | Current: parked because `unibud-live` is abandoned. |
| A2 | Legacy `plugins/files.py` unrestricted path access; legacy calculator resource risk | High if network-exposed | Current: found, not fixed; legacy code outside this task. |
| A3 | Prior report of a hardcoded admin backdoor in uploaded docs | High | Current: not established in current code; re-grep before security sign-off. |
| A4 | `arc-project-one` CI failure cause | Medium | Current: unverified. |
| A5 | Built-in malware scanner only detects EICAR | Medium | Current: found, not fixed. |
| A6 | Oracle Arc gateway had hardcoded UNIBUD agents/prompts/defaults | High | Current: host registration implemented in `oracle_arc/gateway.py`; full 97-test suite passed on the tested source tree. Ignored HTTP socket ResourceWarnings remain. |
| A7 | ORACLE, SPARK, ORBITS and CONCIERGE are one in-process object graph | High | Planned: open. |
| A8 | Storage is SQLite/in-memory; PostgreSQL migrations/constraints/RLS/least privilege required | High | Planned: open. |
| A9 | ORBITS has no HTTP route | Medium | Planned: open. |
| A10 | SPARK lacks user list/correct/delete/retention endpoints and purpose dimension | Medium | Planned: open. |
| A11 | No admin/staff roles, dual approval or rate limiting | High | Planned: open. |
| A12 | 51-agent TypeScript registry needs typecheck, tests and Oracle Arc mapping | High | Planned: open; source not inspected this session. |
| A13 | Audit chain needs externally anchored head | Medium | Planned: open. |
| A14 | No research/statistics provenance model; eleven destinations not started | Planned | Planned: open. |
| A15 | `TrustedAppAssertion` is a stop-gap identity model | High | Planned: open. |

## 5. Important commands
- Current: Oracle Arc suite command: `python3 -W error::ResourceWarning -m unittest discover -s tests -t .`.
- Planned: `unibud-agents` typecheck: `tsc --noEmit -p .`; add and run its actual test command after inspecting package scripts.
- Current: no real Ollama/Qwen or remote model has been exercised; model quality remains unmeasured.
- Current: never merge, deploy or force-push without founder approval.

## 6. Found, not fixed
- Current: `main.py` was not changed. Its CLI currently registers an application from environment variables but does not supply host agent/tool configuration. With the new empty-by-default gateway, chat execution requires an embedding host to register agents/tools/grants. Keep this explicit; do not restore implicit Bud/Concierge defaults.
- Current: README and run instructions were not changed; they may still describe a UNIBUD app registration example.
- Current: No accessible repository named `unibud-agents` was found. The accessible `iamtheoracle/unibud` repository tree has no agent-registry paths; the authoritative source for the 51 definitions remains unidentified.
- Current: `tests/test_http.py` emits ignored `ResourceWarning` messages for unclosed server sockets under the required warning-strict test command; tests still exit successfully. Found, not fixed.
- Current: local checkout was blocked by DNS, but the exact branch archive was retrieved in a hosted Python 3.11.2 environment; branch SHA was checked against the GitHub branch API and the full suite passed 97 tests.

## 7. Statistics
| Metric | Value | As of |
|---|---|---|
| Oracle Arc full test suite | Current: 97 passed at HEAD `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4`; ignored HTTP socket ResourceWarnings observed | 2026-11-14 |
| A6 gateway host defaults | Current: removed from gateway composition; 97-test suite passed; socket-warning follow-up remains | 2026-11-14 |
| Agents mapped from the 51-agent registry | Current: 0 verified; source repository not located | 2026-11-14 |
| Open audit findings | Current: A6 test verification complete with ResourceWarning follow-up; A2-A5 and A7-A15 remain open/parked as above | 2026-11-14 |
| Eleven destinations built | Current: 0 verified | 2026-11-14 |

## 8. Blockers and open decisions
- Current: live branch HEAD was verified as `292129f5ea82f59b58c9d9a3a45afe4ea30eafd4` before this tracker-only update. Local container DNS still cannot resolve `github.com`; the hosted test run downloaded the exact branch archive and confirmed its branch SHA against the GitHub branch API before running the full suite.
- Current: no CI status checks or PR-triggered workflow runs were associated with that HEAD; local/hosted test evidence is the 97-test run above.
- Planned: identity provider choice remains open; do not create a competing identity authority.
- Current: SPARK means user-controlled memory, not orchestration.
- Current: MoneyLeads and UNIBUD remain independent products; Oracle Arc receives no implicit access to either product's data and never moves, holds or settles money.
