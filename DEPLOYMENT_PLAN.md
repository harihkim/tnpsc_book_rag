# Deployment Plan — TNPSC Book RAG (Free-Tier, Multi-Platform)

**Goal:** Deploy the RAG stack for $0 (or near-$0) using:
- Frontend → **Cloudflare Pages** (SvelteKit SPA)
- Database → **Neon Postgres + pgvector**
- Object storage → **Backblaze B2** (keep)
- Web API → **Heroku** (using your credits)
- Ingestion Worker → **Hugging Face Spaces**

**Verdict: FEASIBLE**, with conditions. The stack is *possible* and mostly free, but there are
real constraints (cold starts, build timeouts, a missing S3 adapter, and a mid-refactor
codebase) that shape the plan. Details below, followed by a phased rollout.

---

## 1. Component-by-component feasibility

### Frontend — Cloudflare Pages ✅ (trivially feasible)
- `svelte.config.js` already uses `@sveltejs/adapter-static` with `fallback: 'index.html'` → emits
  a static SPA into `frontend/build/`. This is exactly what Cloudflare Pages wants.
- Cloudflare Pages is **free** (unlimited sites, 500 builds/mo, 100 GB bandwidth).
- **Action needed:** add `frontend/build/_redirects` with `/*    /index.html   200` for SPA
  fallback (Cloudflare Pages honors `_redirects`). The frozen OpenAPI contract (`openapi.v1.yaml`)
  is already there, so the frontend can be built/deployed independently of the backend.
- **Env:** build-time var `VITE_API_BASE` = the Heroku API URL. Set in Pages build settings.
- Build command: `pnpm install && pnpm run build`. Output dir: `build`.

### Database — Neon Postgres + pgvector ✅ (feasible, free tier caveats)
- Neon supports `pgvector` out of the box (`CREATE EXTENSION vector;`). Migration `0001` already
  does this. ✅
- **Free tier:** 0.5 GB storage, compute **auto-suspends after 5 min idle** → cold start ~0.5–1 s
  on next query. For a RAG app with occasional traffic this is acceptable.
- **Critical config:** use the **pooled connection string** (`*-pooler.neon.tech`, with
  `?pgbouncer=true` or the `-pooler` host) in production. The async `psycopg` pool opens many
  connections; Neon's non-pooled endpoint caps at ~4 concurrent on free tier and will refuse
  connections after suspend unless you use the pooler. Set `TNPSC_DATABASE_URL` to the pooled URL.
- **Capacity watch:** `bge-small-en-v1.5` = 384-dim vectors. Tens of thousands of chunks fit in
  0.5 GB, but monitor storage in Neon dashboard; upgrade only if needed (paid).
- **Migrations:** run `alembic upgrade head` as a **Heroku release phase** (or one-off dyno), not a
  long-lived service. The local `compose.yaml` `migrate` service maps to this.

### Object storage — Backblaze B2 ✅ (keep, with one change)
- S3-compatible, free 10 GB, **free egress to Cloudflare** (B2↔Cloudflare partnership). Keep it.
- **Copyright caution:** the repo explicitly notes textbook PDF redistribution rights are unknown.
  Keep the B2 bucket **private**. Do NOT expose it via a public Cloudflare CDN. The FastAPI backend
  should serve artifacts through signed/proxied responses. (Frontend already goes through the API
  for data, so this is consistent.)
- **Blocking gap:** the code currently uses `LocalArtifactStorage` only. `create_artifact_storage()`
  returns `LocalArtifactStorage(settings.artifact_root)` and there is **no B2/S3 adapter yet**
  (Phase 2 in `task.md` is not started; no `boto3`, no `S3ArtifactStorage`). **This must be built
  before multi-service deployment**, because the Heroku API and HF worker must share the same
  artifact store. Local disk on Heroku/HF is ephemeral and per-instance.

### Web API — Heroku (using your credits) ⚠️ (feasible, with dyno-plan choices)
- A `Dockerfile` exists (uv + Python 3.13 + CPU torch wheels). Heroku container deploy via
  `heroku.yml` works.
- **Dyno plan reality:**
  - Heroku **removed the old free tier**. Your "credits" most likely map to the **Eco plan
    ($5/mo, 1000 dyno-hours pool, sleeps after 30 min idle)** or **Basic ($7/mo, always on)**.
    Confirm which your credits cover.
  - Eco = the API **sleeps** → first request after idle waits for boot (~few s). Acceptable for a
    low-traffic demo. Basic = always-on, snappier, costs the credit.
- **Required changes for Heroku:**
  1. Honor **`$PORT`**: current Dockerfile CMD hardcodes `8000`. In production bind to
     `0.0.0.0:$PORT`. FastAPI reads `PORT` via env — add a small entrypoint or set
     `TNPSC_API_PORT=$PORT`.
  2. `heroku.yml` declaring `web` (API) and `worker` (ingestion) process types from the image.
  3. **Release phase** runs `alembic upgrade head` (Neon migrations).
  4. `TNPSC_CORS_ORIGINS` = your `*.pages.dev` (or custom) URL.
  5. Configure a managed OIDC issuer/audience/JWKS endpoint and provision Heroku Key-Value Store
     for shared API rate/concurrency enforcement. Production startup rejects missing auth,
     plaintext `redis://`, or a missing IP-key HMAC secret.
- Heroku ephemeral filesystem: API must write artifacts to **B2**, not local disk (ties back to
  the S3 adapter requirement). The `migrate` job and API both need the B2 + Neon env vars.

### Ingestion Worker — Hugging Face Spaces ⚠️ (feasible but the riskiest piece)
- The worker is a **long-running process** (`python -m tnpsc_book_rag.worker run`) that polls an
  *inbox* directory and imports extraction packages. This fits HF Spaces' process model (a Space
  runs one long-lived command). ✅ conceptually.
- **Risks / conditions:**
  1. **Build timeout (30 min).** The image installs `docling` + `torch` + `sentence-transformers`
     + `transformers`. Even with CPU torch wheels this is a **large image and slow build**. Docker
     Spaces have a 30-min *start* timeout and a long *build* timeout; a first build from scratch
     can blow past limits. **Mitigation:** pre-bake a base image and push to a registry, or switch
     the Space to build from a pre-built image / use the pytorch-cpu index (already set). Keep the
     image lean. Be ready to bump the Space's startup-timeout setting.
  2. **Ephemeral disk.** A Space's local disk is wiped on restart. The worker's `artifacts/` and
     `extraction-inbox/` must NOT live on Space disk. **It must use B2 for artifacts AND pull
     packages from B2** (or a mounted Storage Bucket). Again: the S3/B2 adapter is a prerequisite.
  3. **Sleeps when idle.** Free CPU Spaces sleep after ~15 min inactivity → ingestion stalls. For a
     batch job this is OK (wake it, let it drain the inbox, it sleeps). For continuous ingestion you
     need **always-on / paid hardware**. Given this is a textbook-ingestion batch task, periodic
     wake-and-ingest is fine.
  4. **Inbox source in production.** Locally the worker reads `TNPSC_EXTRACTION_PACKAGE_INBOX` (a
     mounted dir of pre-made packages, produced by `extract_book.py` on a GPU notebook). In the
     cloud, those packages must land in **B2** (e.g., API upload → B2, or you upload packages to B2
     directly). The worker imports from B2 instead of a local dir. **This is the missing production
     ingestion path** — design it as part of the S3 adapter work.
- **Good news:** no worker message broker is needed. The worker remains poll-based (`run_once()`).
  The Redis/Valkey service required by the web API is only for shared request-rate and concurrency
  enforcement; it is not an ingestion queue. ✅

---

## 2. Critical blockers to resolve BEFORE deploy

| # | Blocker | Why it matters | Owner step |
|---|---------|----------------|-----------|
| B1 | **No B2/S3 artifact adapter** (Phase 2 in `task.md` not started) | API + worker must share artifacts & inbox; Heroku/HF local disk is ephemeral | Implement `S3ArtifactStorage` + factory switch on env; add `boto3` |
| B2 | **Worker inbox is a local dir** | In cloud there's no shared local dir; packages must come from B2 | Add a B2-backed package source (or mount B2 as inbox) |
| B3 | **Repo is mid-refactor** (`task.md` Phase 1 folder rename) | `database_persistence/migrations` duplicates `db/migrations`; a broken refactor breaks `alembic upgrade head` in prod | Finish/verify the rename + `pytest`; ensure single migrations source |
| B4 | **Heroku `$PORT` hardcoded to 8000** | Heroku assigns random `$PORT`; app won't be reachable | Bind to `$PORT` in prod entrypoint |
| B5 | **Neon non-pooled connection** | Free-tier connection caps + suspend → refused connections | Use pooled endpoint URL in `TNPSC_DATABASE_URL` |
| B6 | **Copyright** | TN textbook PDFs may not be redistributable | Keep B2 private; serve via API proxy only |

---

## 3. Reference topology (production)

```
                 ┌─────────────────────┐
   Browser ─────►│  Cloudflare Pages   │  (static SvelteKit SPA, free)
                 │  frontend/build/    │
                 └─────────┬───────────┘
                           │ HTTPS / REST (CORS: pages.dev)
                           ▼
                 ┌─────────────────────┐
                 │  Heroku Web (API)   │  Eco/Basic dyno, Docker image
                 │  fastapi run :$PORT │  - reads/writes Neon (pooled)
                 └──┬───────────────┬──┘  - reads/writes B2 (private)
                    │               │
        migrations  │               │  upload source PDFs / packages
     (release phase)│               │  ───────────────┐
                    ▼               ▼                  ▼
              ┌──────────┐    ┌──────────────┐   ┌──────────────┐
              │  Neon PG │    │ Backblaze B2 │   │ GPU notebook │
              │ +pgvector│    │ (private)    │   │ extract_book │
              └──────────┘    └──────┬───────┘   │ → package.zip│
                                    │            └──────────────┘
                                    │ packages + artifacts
                                    ▼
                 ┌─────────────────────────────┐
                 │  HF Spaces Worker (Docker)   │  long-running poll loop
                 │  python -m ... worker run    │  - imports from B2 inbox
                 │  writes embeddings → Neon     │  - writes artifacts → B2
                 └─────────────────────────────┘
```

Both Heroku API and HF worker talk to the **same Neon** and **same B2** — that shared state is
what makes two separate free platforms act as one system.

---

## 4. Phased rollout

### Phase 0 — Prereqs (resolve blockers B1–B6)
1. Finish the folder-rename refactor; run `pytest`; ensure `alembic upgrade head` works locally. (B3)
2. Implement `S3ArtifactStorage` (boto3) + `create_artifact_storage()` env switch. (B1)
3. Add a B2-backed extraction-package source for the worker (replace local inbox mount). (B2)
4. Make the API/Docker entrypoint honor `$PORT`. (B4)

### Phase 1 — Neon + B2 (data layer)
5. Create Neon project; run `CREATE EXTENSION vector` (migration 0001 covers it).
6. Create B2 bucket (private); generate app-key (read/write).
7. Smoke-test locally: point `TNPSC_DATABASE_URL` (pooled) + B2 creds at cloud; `alembic upgrade head`;
   upload one book via API; confirm it lands in B2 and embeddings in Neon.

### Phase 2 — Heroku (API)
8. `heroku.yml`: `build.docker` + `web` + `worker` process types; `release: alembic upgrade head`.
9. Set config vars: `TNPSC_DATABASE_URL` (pooled), `TNPSC_ARTIFACT_ROOT` → B2 mode, B2 keys,
   `TNPSC_CORS_ORIGINS` = Pages URL, `TNPSC_ENVIRONMENT=production`, `PORT` (auto), the
   `TNPSC_OIDC_*` values, `TNPSC_AUTH_ENABLED=true`, `TNPSC_RATE_LIMITING_ENABLED=true`,
   `TNPSC_RATE_LIMIT_URL` from Heroku Key-Value Store, and a random
   `TNPSC_RATE_LIMIT_IP_HMAC_SECRET`.
10. Deploy: `git push heroku main` (container). Verify `/health/ready`.

### Phase 3 — HF Spaces (Worker)
11. Create Docker Space; `Dockerfile` reuse from backend; `start` command =
    `python -m tnpsc_book_rag.worker run` with B2 + Neon env vars (Space Secrets).
12. Pre-build/push a base image if the 30-min build is at risk; raise startup-timeout if needed.
13. Attach a Storage Bucket only if you keep any local state; otherwise B2 is the only store.
14. Drop one extraction package into B2; confirm the worker imports it (Neon rows + B2 artifacts).

### Phase 4 — Cloudflare Pages (Frontend)
15. Add `frontend/build/_redirects`: `/*    /index.html   200`.
16. Pages project → connect repo, build `pnpm install && pnpm run build`, output `build`,
    env `VITE_API_BASE` = Heroku URL. Configure the frontend as a public OIDC client using
    Authorization Code + PKCE; it sends the access token as `Authorization: Bearer`.
17. Verify SPA routes + CORS from Pages → Heroku.

### Phase 5 — Hardening
18. Secrets only in platform env/Spaces Secrets (never committed). `.env` already gitignored. ✅
19. Keep B2 private; API proxies artifact reads. (B6)
20. Add a simple "wake worker" path (HF free Spaces sleep) — e.g., a scheduled ping or manual wake
    for batch ingestion; or accept Eco-style sleep for the API.

---

## 5. Cost summary (free-tier assumptions)
- Cloudflare Pages: **$0**
- Neon (free): **$0** (0.5 GB, autosuspend)
- Backblaze B2: **$0** (≤10 GB, free Cloudflare egress)
- Heroku: **$0–$7/mo** depending on whether your credits cover Eco ($5) or Basic ($7); Eco sleeps
- HF Spaces (CPU, free): **$0** (sleeps when idle); paid hardware only if you need always-on worker

**Net:** deployable at **$0** if your Heroku credits cover an Eco dyno and you accept sleep/cold-start
behavior; the only hard cost risk is if you need always-on on both Heroku and HF (then ~$12–$20/mo).

---

## 6. Open questions for you
- Q1: What exactly do your Heroku "credits" map to — Eco ($5/mo) or Basic ($7/mo)? This decides
  whether the API sleeps.
- Q2: Will ingestion be **batch** (occasional, worker can sleep) or **continuous** (needs always-on
  worker → paid HF hardware)?
- Q3: Do you already have a Neon project + B2 bucket/keys, or should the plan include provisioning
  commands?
- Q4: OK to keep B2 **private** and proxy artifacts through the API (recommended for copyright)?
