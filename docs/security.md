# Beyonder security posture

This is a personal-use research project, but npm's recent compromises (the
Shai-Hulud worm, the qix/chalk credential-stealing batch, postinstall-driven
crypto miners) raised the bar on what counts as "good enough."

## Threat model

| Threat | In scope? | Mitigation |
|---|---|---|
| Malicious npm postinstall scripts | YES | `ignore-scripts=true` in `.npmrc` + `npm_config_ignore_scripts=true` env in Docker. Never run `pnpm install` on host. |
| Compromised npm package mid-flight | YES | `frozen-lockfile=true` + `save-exact=true` — only the exact versions in `pnpm-lock.yaml` install. New versions require a deliberate lockfile bump. |
| Postinstall worm reading host secrets | YES | Frontend tooling runs only inside the dev/build Docker containers. Containers have `cap_drop: ALL`, `no-new-privileges`, no host bind mount outside `frontend/`. They cannot see `.env`, browser cookies, SSH keys, or anything else on the host. |
| Leaked Gemini API key | YES | `.env` is git-ignored. `.env.example` is the only checked-in copy. Backend reads via pydantic-settings and never logs the key. |
| SQL injection / SSRF via ingest URL | YES | All DB access goes through SQLAlchemy parameterised queries. URLs pass through Playwright (sandboxed Chromium) — no raw HTTP from arbitrary user input. |
| Prompt injection in scraped chapter text | PARTIAL | We pass scraped text to Gemini, which is *not* a tool-using agent in the dangerous sense — it cannot exfiltrate files or hit other APIs. Worst-case the model emits nonsense in the glossary; the deterministic critic still flags drift. |
| Container escape | LOW | We don't run untrusted code in containers — only our own dev server and `next build`. |
| Out of scope | — | Browser-side XSS (the frontend renders only text from your own backend), DDoS, key compromise of `gemini.api.dev`, supply-chain compromise of `next` itself before our pinned hash. |

## npm hardening, concrete

1. **The host never runs npm or node directly.** Every `pnpm install`,
   `pnpm build`, `pnpm dev` happens inside a Docker container. Verify with:
   ```powershell
   Get-Command pnpm -ErrorAction SilentlyContinue   # should be empty
   Get-Command npm  -ErrorAction SilentlyContinue   # should be empty (or system-wide unused)
   ```
2. **Postinstall scripts are blocked.** `frontend/.npmrc` sets
   `ignore-scripts=true`. Both Dockerfiles also pass `--ignore-scripts` to
   `pnpm install`. The `docker-compose.yml` sets
   `npm_config_ignore_scripts=true` as a third layer.
3. **Versions are pinned.** `package.json` uses exact versions (no `^`/`~`).
   `pnpm-lock.yaml` is generated inside Docker on first run; commit it so
   subsequent installs are bit-exact.
4. **Dependency surface is minimal.** Three runtime deps (`next`, `react`,
   `react-dom`), four dev deps (types + TypeScript). No CSS framework, no
   force-graph lib, no UI kit. The whole frontend is hand-written.
5. **Container privileges are dropped.** `cap_drop: ALL` and
   `security_opt: no-new-privileges` in `docker-compose.yml`. The container
   cannot mount, bind ports >1024, or write outside `/app` (its bind mount).
6. **Audit before bumping.** When you do bump a version:
   ```powershell
   docker compose run --rm frontend-dev pnpm audit
   docker compose run --rm frontend-dev pnpm why <pkg>
   ```
   And cross-check the new release on https://socket.dev/ if it's not a
   major-vendor package.
7. **No prod Node runtime.** `next.config.mjs` uses `output: "export"`. The
   production deploy serves static HTML/JS/CSS — there is no `node` process
   handling user requests, so any future postinstall malware has zero blast
   radius in prod.

## Backend (Python) hardening

- All deps pinned in `requirements.txt`. No `>=`.
- `playwright install chromium` runs the official upstream binary. Pin the
  Playwright Python version (`1.49.0`); the Chromium build it installs is
  determined by that pin.
- The scraper uses Playwright (`headless=True`) with a clean context, no
  cookies, no shared profile.
- Postgres + Qdrant run in Docker on `localhost`. Both are unauthenticated by
  default. Do not bind their ports to anything but `127.0.0.1` if you ever
  put this on a server.
- Logging never includes the Gemini key or full request bodies.

## Secrets management

- `.env` is git-ignored. `.gitignore` also catches `*.key`, `*.pem`,
  `secrets/`.
- For Supabase / Qdrant Cloud, set the URL+key via `.env`, not in code.
- For CI, use environment secrets, never commit. If you adopt CI later,
  ensure log output doesn't print env vars.

## Incident response checklist

If you suspect a compromise (or just want to be paranoid after a vague npm
advisory):

1. Stop containers: `docker compose down`.
2. Inspect the running container's process list (post-mortem):
   `docker compose logs frontend-dev | rg postinstall`.
3. Rotate `GEMINI_API_KEY` at https://aistudio.google.com/apikey.
4. Wipe the volume: `docker volume rm beyonder_frontend_node_modules beyonder_frontend_pnpm_store`.
5. `pnpm-lock.yaml` was diffed against last-known-good — if changed, revert and
   rebuild. If unchanged, the issue is upstream, not in your repo.
6. Re-clone the repo into a fresh dir before re-installing. Don't trust a
   compromised working tree.

## Further reading

- [Socket.dev advisories](https://socket.dev/)
- [Open Source Security Foundation Best Practices](https://openssf.org/)
- [pnpm security FAQ](https://pnpm.io/security)
