# UNIBUD BUILD TRACKER
Last updated: 2026-11-14. Labels: Current = verified in code during this session; Planned = agreed, not built; Concept = name only.
Rule: trust code over notes. Re-verify claims before relying on them.

## 1. Stopped at / Next exact step
- Current: Oracle Arc A6 host-registration implementation is present in `oracle_arc/gateway.py`; the tested source commit is `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020`; the source-code HEAD verified in this pass was `03c8d3da080ad8133f7b35c5e131bc45e2497296` on `feat/oracle-arc-core`; the subsequent tracker refresh is documentation-only.
- Current: `oracle_arc/gateway.py` no longer defines Bud/Concierge prompts, imports Concierge's product-specific tool factory, auto-registers product agents, auto-grants product tools, or defaults `/v1/chat` and `/v1/complete` to Bud.
- Current: `Arc` accepts host-provided `app_credentials`, `agent_specs`, `tool_specs`, and explicit `tool_grants`; invalid grants referencing missing agents/tools are rejected.
- Current: `tests/helpers.py` now supplies the Bud/Concierge-shaped test fixtures as test-host registrations, not gateway defaults. `tests/test_gateway.py` adds host-isolation/configuration tests. `tests/test_http.py` now supplies explicit agents and checks missing-agent rejection.
- Current: Full suite ran against HEAD `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020` in a hosted Python 3.11.2 environment: `Ran 97 tests in 10.218s`, `OK`. `ResourceWarning` messages for unclosed HTTP test sockets were emitted as ignored exceptions; suite exit code was 0. A6 behavior is now test-verified at this commit.
- Current: `iamtheoracle/unibud-app` is named as the source-of-truth repository in its own `UNIBUD_IMPLEMENTATION_HANDOFF.md`; current `main` HEAD verified as `3029a8761b5e42b3880f0392640abf377ba325a3`. Its `src/lib/agents/contracts.ts` defines 16 `AgentId` values and `src/lib/agents/registry.ts` contains 16 definitions, not 51.
- Current: `iamtheoracle/unibud-live` is reference-only by founder decision. Its `src/lib/agents/registry.ts` contains 15 definitions; its handoff says the organization register has 51 identities, but no 51-entry typed registry was verified there. Do not modify this repository.
- Planned: NEXT EXACT STEP — recover the authoritative 51-role catalog/registry source. Do not map 16 UNIBUD-specific agents as if they were 51 Oracle Arc agents, and do not import UNIBUD agent prompts or product semantics into Oracle Arc.
- Planned: Then implement Oracle Arc PostgreSQL storage and migrations (A8).
- Founder decision: `unibud-live` is abandoned and reference-only; no new feature work there.

## 2. Repositories and verified state
| Repo | Branch / commit | State | Tests |
|---|---|---|---|
| `arc-project-two` | Current: source code verified on `feat/oracle-arc-core` at `03c8d3da080ad8133f7b35c5e131bc45e2497296`; tracker refresh is a documentation-only commit atop that source | Current: gateway uses host-supplied app/agent/tool/grant configuration; storage remains SQLite/in-memory and ORBITS storage is in-memory. | Current: 97 tests passed on tested source commit `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020`; final run 10.218s; ResourceWarning messages remain visible. |
| `unibud-live` | Current: abandoned/reference-only per founder decision | Current: no new feature work authorized. | Current: not run. |
| `unibud-app` | Current: `main` @ `3029a8761b5e42b3880f0392640abf377ba325a3`; named as source of truth by its handoff | Current: `src/lib/agents/contracts.ts` and `src/lib/agents/registry.ts` define 16 agents, not 51. | Current: not run in this session; remote source inspected only. |
| `arc-project-one` | Current: previous working-copy snapshot, not part of this task | Current: no changes in this session. | Historical: 141 passed under a local vitest-compatible shim, not real vitest. |

## 3. Fix queue
1. Current: A6 gateway host-registration slice is implemented and the full suite passed 97 tests at HEAD `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020`; ResourceWarning cleanup remains a follow-up.
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
| A12 | 51-agent TypeScript registry needs typecheck, tests and Oracle Arc mapping | High | Current: `unibud-app` source inspected; only 16 IDs/definitions found. A complete 51-entry source remains unverified. Planned: open. |
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
- Current: No accessible repository named `unibud-agents` was found. `iamtheoracle/unibud-app` is identified by its handoff as the source of truth, but its checked-in registry and contracts contain only 16 agents. `iamtheoracle/unibud-live` contains 15 definitions and an outdated orchestration interpretation of Spark; it remains reference-only. The full 51-role catalog remains unidentified.
- Current: `tests/test_http.py` emits ignored `ResourceWarning` messages for unclosed server sockets under the required warning-strict test command; tests still exit successfully. Found, not fixed.
- Current: local checkout was blocked by DNS, but the exact branch archive was retrieved in a hosted Python 3.11.2 environment; branch SHA was checked against the GitHub branch API and the full suite passed 97 tests.

## 7. Statistics
| Metric | Value | As of |
|---|---|---|
| Oracle Arc full test suite | Current: 97 passed at HEAD `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020`; ignored HTTP socket ResourceWarnings observed | 2026-11-14 |
| A6 gateway host defaults | Current: removed from gateway composition; 97-test suite passed; socket-warning follow-up remains | 2026-11-14 |
| Agents mapped from the 51-agent registry | Current: 0 verified; unibud-app contains 16 typed definitions, not 51 | 2026-11-14 |
| Open audit findings | Current: A6 test verification complete with ResourceWarning follow-up; A2-A5 and A7-A15 remain open/parked as above | 2026-11-14 |
| Eleven destinations built | Current: 0 verified | 2026-11-14 |

## 8. Blockers and open decisions
- Current: source-code HEAD at verification was `03c8d3da080ad8133f7b35c5e131bc45e2497296`; the subsequent tracker refresh changes documentation only, and application source remains the previously tested `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020` tree. Local container DNS still cannot resolve `github.com`; the hosted test run downloaded the exact source archive and confirmed its SHA against the GitHub branch API before running the full suite.
- Current: no CI status checks or PR-triggered workflow runs were associated with that HEAD; local/hosted test evidence is the 97-test run above.
- Planned: identity provider choice remains open; do not create a competing identity authority.
- Current: SPARK means user-controlled memory, not orchestration; the UNIBUD handoff/legacy registry descriptions that assign Spark orchestration are outdated and must not be copied into Oracle Arc.
- Current: `unibud-app` package scripts expose `typecheck: tsc --noEmit` and `test`; neither command was executed in this session. The task's named `unibud-agents` package/repository remains unavailable.
- Current: MoneyLeads and UNIBUD remain independent products; Oracle Arc receives no implicit access to either product's data and never moves, holds or settles money.


## 9. UNIBUD + Oracle Arc reference capability inventory (research-only)
- Concept: This section records the 13 reference platforms supplied by the founder as capability references, not dependencies, copied brands, provider commitments, or evidence of implementation.
- Concept: Source coverage is 11/13 platforms with vendor or primary documentation reviewed: Day AI, Robin, Viberate, Restream, WeTransfer, Mastercard Developers Agent Toolkit, Prefect, PointOne, Specter, TinyFish, and Firecrawl.
- Concept: CREparser and Revalidata capabilities remain founder-supplied descriptions only; their complete product implementations and accuracy claims were not independently verified.
- Concept: Day AI patterns — source-linked entity/context graph, temporal provenance, person/agent permission inheritance, per-tool read/write controls and approval gates. Potential native consumers: Connect, Board, Quarter, Wayward, Operations; Bud/Concierge/ORACLE only through explicit, scoped access. SPARK remains user-controlled memory, not a shared orchestration graph.
- Concept: Robin patterns — room/desk/resource reservations, interactive floor maps, check-in, visitor management, access policies, occupancy and historical analytics/export. Potential owners: Operations and participating institutions; Wayward only for approved trip/event resource coordination.
- Concept: Viberate patterns — artist/song/playlist/festival/venue discovery, cross-channel streaming/social/radio metrics, audience geography/demographics, ranking, comparisons and alerts. Potential owners: Connect and Riff; Wayward for music events; ORACLE may research only with permitted sources and provenance.
- Concept: Restream patterns — broadcast/event lifecycle, destination management, chat/moderation, viewer and engagement analytics, recordings, transcription and clipping. Potential owner: ORBITS media processing; eligible Connect, Riff, Square/Quad or Wayward surfaces only where existing approved experiences require it.
- Concept: WeTransfer patterns — upload/transfer lifecycle, recipient restrictions, passwords, expiry, previews, download status, revocation and recovery. Potential owner: shared secure file-delivery service used by Bud, Board, Connect, Square, Operations and authorized Concierge workflows. No public developer API was verified in this research.
- Concept: Mastercard Developers Agent Toolkit patterns — API/service catalogue discovery, API operation listing, documentation retrieval and OAuth/Open Finance integration guides. Potential owner: developer administration and API documentation; ORACLE may discover approved tool documentation. This toolkit is not evidence of payment-rail access or financial authorization.
- Concept: Prefect patterns — workflow definitions/deployments, scheduler, event triggers, work pools, workers, execution states, concurrency, retries, logs and notifications. Potential owner: native Operations workflow runtime; ORACLE can request bounded workflows through grants; SPARK is not the scheduler.
- Concept: PointOne patterns — professional time capture, matter-linked work records, billing-rule extraction/enforcement, pre-bill review, reviewer routing/comments and time analytics. Potential owner: Operations and organizations that explicitly need professional-services controls; do not assume all UNIBUD institutions are law firms.
- Concept: Specter patterns — company, people, investor and transaction intelligence; funding/M&A/IPO history; growth/revenue estimates; talent and investor-interest signals; saved searches, network context and sourced API feeds. Potential owners: Connect and Quarter; Board/Operations only for legitimate organization research; ORACLE research requires explicit source, privacy and access controls.
- Concept: CREparser patterns (founder-supplied, not independently verified) — lease upload/classification, clause and term extraction, rent/financial-term validation, document comparison, consent analysis and human review. Potential owners: Operations/facilities and relevant institutional document workflows; Board only where institution facilities records are authorized.
- Concept: Revalidata patterns (founder-supplied, not independently verified) — contract understanding, obligation extraction, deadline/notice detection, source-passage citations, obligation assignment and deadline tracking. Potential owners: Operations, institutional administration, Quarter and authorized Concierge service requests; ORACLE can extract/evidence but not provide guaranteed legal conclusions.
- Concept: TinyFish patterns — isolated browser sessions, controlled browser automation, reusable saved session state, multi-step navigation and structured extraction. Potential owner: isolated browser-worker service for approved Connect, Board, Wayward and Concierge research tasks; require domain allowlists, user/organization authorization, credential isolation and audit. Never bypass access controls.
- Concept: Firecrawl patterns — search, scrape, crawl, map, structured extraction, document parsing, browser interaction and page/web-scale change monitoring. Potential owner: native ingestion/discovery pipeline for Connect, Board, Wayward and Quarter; ORACLE research uses provenance-bearing, untrusted source content.
- Planned: Build a capability-to-service blueprint only after the inventory is reconciled against founder-approved space definitions and the authoritative 51-agent registry. Do not silently convert these references into new product features or agent identities.
- Planned: Native services to evaluate as shared infrastructure: entity/context records and provenance; ingestion and deduplication; permission-aware search; workflow scheduler/queues/workers; document intelligence; secure file delivery; media processing; resource/workforce management; developer/API catalogue; analytics and audit.
- Current: No UNIBUD or Oracle Arc application source was changed by this research. No reference platform has been integrated or adopted as a runtime dependency.


## 10. Latest continuation verification — 2026-11-14
- Current: GitHub branch ref for `feat/oracle-arc-core` was re-read before the tracker refresh; source HEAD was `03c8d3da080ad8133f7b35c5e131bc45e2497296`.
- Current: That source HEAD has commit message `docs: record native capability research inventory` and changes only `docs/BUILD_TRACKER.md`. The tracker refresh itself is also documentation-only; it does not alter application source.
- Current: Combined commit statuses returned an empty list, and the commit workflow-run query returned no runs. No CI pass is claimed for this HEAD.
- Current: `oracle_arc/gateway.py` still accepts host-provided `agent_specs`, `tool_specs`, and `tool_grants`; it does not define default Bud/Concierge agents or prompts. `tests/test_gateway.py` contains the host-registration and empty-core tests.
- Current: `tests/test_http.py` starts a `serve_forever` thread and registers shutdown/server-close cleanups, but does not retain and join the serving thread. This is a plausible cause of the historical socket `ResourceWarning`, not a proven root cause.
- Current: The historical 97-test result applies to source commit `c0e0d9b4b08ef9e155172a0f38fbb2fa3949c020`, not the current branch HEAD. Tests were not run in this continuation because there is no local checkout and the prior container checkout attempt failed DNS resolution; no before/after test result is claimed.
- Current: `iamtheoracle/unibud` main is `3ce92aa1dad1e40520de4084e2a1cca3677b8e76`; both `docs/BUILD_TRACKER.md` and `claude/BUILD_TRACKER.md` return 404 there. Project-file search also returned no attached tracker.
- Current: `iamtheoracle/unibud-app` main is `3029a8761b5e42b3880f0392640abf377ba325a3`. Its `src/lib/agents/contracts.ts` and `src/lib/agents/registry.ts` contain 16 agent definitions, not an authoritative 51-entry catalogue. Its package exposes `typecheck` and `test` scripts; neither was run in this continuation.
- Found, not fixed: `unibud-app/src/lib/agents/registry.ts` and `UNIBUD_IMPLEMENTATION_HANDOFF.md` describe SPARK as a coordinator/orchestrator. This conflicts with the founder's controlling decision that SPARK is user-controlled memory. Do not copy that definition into Oracle Arc. The app registry is outside this bounded gateway/test-cleanup slice.
- Found, not fixed: No repository named `unibud-agents` was returned by repository search. The 51-role catalogue remains unavailable; do not invent the missing identities.
- Planned: The next code change remains the narrowly scoped HTTP test-thread cleanup in `tests/test_http.py`, but it must be made only when a runnable checkout is available so the warning-strict test command can be run before and after.
- Planned: After that test cleanup is verified, continue Task 2 only when the authoritative 51-role catalogue is available; then perform typecheck, add tests and map verified agents through explicit Oracle Arc host registration. Do not begin the later PostgreSQL/engine stages ahead of Task 2.
