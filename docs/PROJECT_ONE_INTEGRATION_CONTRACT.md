# Project One integration contract

## Repository boundary

- `iamtheoracle/arc-project-one` owns the product shell, navigation, authenticated user session and presentation.
- `iamtheoracle/arc-project-two` owns the Oracle Arc platform API, tenant/application identity, agent execution, memory policy and trusted runtime.
- Project One must not duplicate Project Two's tenant, credential, execution or policy databases.

## Current application API

Project One's typed client targets the application-credential routes under `/v1/platform`:

| Capability | Method and path | Authentication |
|---|---|---|
| Resolve current application identity | `GET /identity` | Application bearer credential |
| Read scoped memories | `GET /memories?limit=50` | Application bearer credential + memory capability |
| Save scoped memory | `POST /memories` | Application bearer credential + memory capability |
| Submit an agent task | `POST /agent-tasks` | Application bearer credential + task capability |

The credential must be issued by the owner control plane and injected into Project One by its authenticated server/session layer. Never put it in source code, URLs, browser storage, analytics, logs or client-side error reports. For browser-only deployments, use a same-origin backend-for-frontend (BFF) to hold the credential and forward narrowly allowlisted requests.

## Navigation contract

Project One defines navigation identifiers and route paths in `src/domain/arcNavigation.ts`. A navigation item marked `planned` is not a working feature and must remain hidden by default. The Project One shell may render planned entries as disabled only in an explicit preview/development mode.

The current Project Two API supports identity, memory and scoped task submission. Agent catalog/version management, model routing UI, tool grants, detailed execution history and usage dashboards must not be presented as operational until their corresponding authenticated API contracts and tests exist.

## Deployment requirements

1. Configure a single HTTPS API origin per environment; do not accept an arbitrary API origin from query parameters or user-controlled content.
2. Configure CORS only for exact trusted Project One origins. Do not use wildcard origins with credentials.
3. Prefer a BFF for browser clients. If a browser must call Project Two directly, use short-lived application credentials and a narrowly scoped CORS allowlist.
4. Keep owner credentials separate from application credentials. Project One must never call owner-only tenant, application, credential-issuance or revocation endpoints using an end-user browser.
5. Treat `401` as an expired/invalid session and `403` as a missing capability; do not silently retry either with broader credentials.
6. Render loading, empty, denied, unavailable and error states distinctly. Never replace API failures with fabricated success data.
7. Pass cancellation signals when a screen unmounts or a request is superseded. Do not retry task submission unless the caller supplies an idempotency mechanism supported by the API.

## Integration status

This is an integration contract, not a production connection. Project One's current repository contains domain TypeScript but no application shell, route tree, package manifest, or navigation component. The navigation model and API client are ready for the shell to consume; a visual sidebar/header cannot be wired until that shell exists. No production origin, credential, CORS policy or deployment setting has been assumed or changed.
