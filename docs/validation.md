# Validation record

This file records checks performed at their stated dates. Counts, package policies, public-release descriptions and test totals below are historical results, not the current deployment or competition rules. Current behavior is documented in [API contract](api-contract.md), [evaluation](evaluation.md), [deployment](deployment.md) and [operations](operations.md). Dataset generation lives in the data repository; merging to main deploys the web server automatically with the mock evaluator (see deployment.md), but does not establish that the scoring machine has been deployed or re-tested.

## Model ZIP submission, queue worker and isolated scoring — 2026-10-02

Verified on a Windows 11 development PC with Docker Desktop (8 CPUs, 16 GB), using FAKE demo data from `scripts/make_demo.py`. Not yet verified: the real dataset, the data team's inference contract, a Linux host, the club-room computer, real model sizes and timings.

- Unit/API tests: 76 passed on the host and 76 passed inside the `api` container (`pytest.docker.ini`). Covers issued-account login, removed registration, ZIP intake rejections, team-wide limit shared by several accounts, queue worker, failure codes, stale-job recovery, requeue, attempt refund, freeze, ban, tie order, both final-ranking rules, dataset approval/verify/lock, account sheet sync, ZIP checks, container command flags.
- Next.js production build and TypeScript check passed in the `web` image build.
- `scripts/postgres_smoke.py` on real PostgreSQL in a disposable database: `0001 -> 0002` migration with prototype rows, issued accounts, two accounts of one team submitting at the same moment with limit 1 (exactly one `202`, one `429`), worker scoring, leaderboard, private-score protection, close/finalize, audit log, then downgrade to `0001` and upgrade again.
- Through the gateway with the mock evaluator: login, `queued -> running -> succeeded`, mock failure, wrong extension `415`, non-ZIP `422`, leaderboard, quota, `/api/datasets/test` `404`.
- Upload size: through the Next.js proxy a 15 MB ZIP failed (10 MB proxy body limit). Through the nginx gateway 15 MB and 300 MB were accepted (`202`, 300 MB in about 3 s locally) and 520 MB was refused with `413 zip_too_large`.
- Real Docker evaluator (`docker-compose.evaluator.yml`, limits lowered to 20 s and 512 MB for the test): a valid submission scored with real Macro F1 against the fake labels; a crash gave `runtime_error` with the traceback visible to the organizer only; malformed output `output_invalid`; a symlink planted as the output file `output_missing`; 20 MB output `output_invalid`; memory hog `out_of_memory`; a 120 s sleep `timeout` after 23 s; restarting the worker mid-run re-queued the submission and finished it on attempt 2.
- Isolation probe run as a submission: no network or DNS, PostgreSQL unreachable, no Docker socket, no labels file anywhere, no secret environment variables, `/submission`, `/input` and `/` read-only, running as uid 65534, only `/tmp` writable, `/input` contained only `test.csv`.
- Mock scores did not appear on the leaderboard once the evaluator was `docker`.
- API container checked: no `/srv/data/private`, no docker CLI. Worker in mock mode: uid 10001, no Docker socket.
- Browser (desktop 1024 px and mobile 375 px): login dialog, case-insensitive ID, ZIP upload with confirmation, receipt ID, automatic status refresh to the score, remaining attempts; organizer overview, account issue with one-time password, submissions filter and log view, dataset approval view, audit log. No horizontal overflow at 375 px.

### Submission file table (migration 0003) — 2026-10-02

- 82 tests passed. New coverage: file record written with the submission, team storage usage, organizer-only download with audit, delete rules (ranked and pending files protected, reason required, score and attempt kept, no re-scoring afterwards), disk/database comparison (missing, changed size, orphan).
- `postgres_smoke.py` on real PostgreSQL: a ZIP submission recorded under the 0002 schema received a file record after upgrading to 0003, and downgrading to 0002 restored the columns.
- Applied to the running stack after a `pg_dump` backup: `alembic_version` 0003, 11 accounts unchanged, public address still serving.
- Browser on a separate throwaway stack: team storage usage shown, "ZIP 받기" returned the stored ZIP, delete was disabled for the ranked submission, deleting another asked for a reason and then showed "파일 삭제됨" with who, when and why, and the file check reported the remaining ZIPs as consistent.

## CSV prototype and dataset records — 2026-10-01

- Official CATH v4.4 FASTA (6,552,513 bytes) and classifications (44,606,235 bytes) downloaded and SHA-256 recorded.
- Actual dataset generated: 32,545 samples / 20 classes; train 26,048, test 6,497.
- Dataset audit: no ID, sequence or C.A.T.H overlap between train/test; Public/Private disjoint; all 20 labels represented in both evaluation partitions.
- Backend: 24 tests passed; real CATH files used in dataset tests. Scoring/cleaning edge cases use small unit fixtures only.
- CPU 3-mer TF-IDF + One-vs-Rest balanced Logistic Regression: exploratory random-holdout Macro F1 0.31038; 6,497 predictions generated. This validation is not H-aware and must not be treated as a hidden-test estimate.
- The actual trained baseline CSV was accepted and scored through the PostgreSQL API smoke test: Public Macro F1 **0.16247**.
- Next.js 16.3.8 production build and TypeScript checks passed; npm audit reported 0 vulnerabilities at installation.
- `docker compose up --build -d`: web, API and PostgreSQL running. API/PostgreSQL healthy; actual same-origin web proxy `/api/health` returns dataset_ready=true.
- Real PostgreSQL disposable database smoke: Alembic migration, registration/login, downloads, scoring, concurrent daily quota, Public/Private authorization, close/finalize, immutable final state, OpenAPI passed. Test database is removed afterward, leaving the real competition unpopulated and closed.
- Browser: desktop layout inspected, 390px mobile layout inspected, real Data/Evaluation/Rules/Submit UI accessible. Product preview saved separately in outputs.

Re-run the PostgreSQL test (requires CREATE DATABASE permission; intended for local Docker only):

```bash
docker compose exec -T -w /srv/apps/api api python /srv/scripts/postgres_smoke.py
```

Only the randomly named test database is dropped. Competition data is not modified. Unit test output currently includes one upstream Starlette/httpx deprecation warning; no failing tests.

## Scheduled release and temporary HTTPS verification

- 30 tests passed after adding server-enforced dataset release windows (including exact start/end boundaries, unset schedule, manual close, finalized state, Range requests and metadata hiding).
- Production Docker build and PostgreSQL disposable-database end-to-end smoke passed with Secure cookies.
- Temporary HTTPS endpoint verified: homepage/API 200, all five dataset downloads 403 before start, metadata null, foreign Origin rejected, admin endpoint requires authentication.
- Generated public CSV/statistics/charts are no longer tracked in new Git commits. Historical versions remain in the organizer-only private repository.


## Structure-input dataset revision

- Task is now observed sequence + experimental Cα structure/8 Å graph -> CATH Architecture, not sequence-only folding prediction.
- Official v4.4 S40 PDB archive and ATOM FASTA downloaded with SHA-256 provenance. Exact PDB/ATOM sequence matching and Cα coverage filtering.
- 26,961 samples / 20 classes; train 21,568, test 5,393. Every published graph audited for sequence correspondence, coordinate/mask correctness, full radius-edge set, distances, backbone segmentation and label-free features.
- Fixed case-insensitive macOS cache collisions for case-sensitive PDB chain IDs using hex-encoded cache filenames, regenerated before publication, and added a regression test.
- 42 backend/data tests passed. Existing Starlette/httpx deprecation warning only. Production Next.js build passed.
- Participant starter-kit Python script and all notebook code cells executed using only packaged public files. CPU run ~1.5 seconds here, H-group validation Macro F1 0.31254. This timing is hardware-dependent and excludes feature generation. GNN training speed has not been benchmarked.
- Real PostgreSQL disposable-database flow passed with 5,393 baseline predictions: Public Macro F1 0.27128028883106725, concurrent quota, private-score protection, downloads with Range, finalize and OpenAPI. No production accounts or submissions were created.
- Previous sequence-only data archived locally under ignored work/sequence-only-archive before switching the still-closed, empty competition. No production schedule was opened for testing.
- Separate loopback-only test API/database used to inspect the open Data page, starter kit and graph download cards; actual shared site remains locked until the configured start time.
- Rounded decorative SVG coordinates to avoid cross-runtime float precision hydration mismatches seen during browser QA.

- Follow-up: code-only baseline_code.zip is publicly downloadable before/after the event; explicit six-file allowlist and empty notebook outputs verified. Event data/starter kit remain behind the same release gate. Added a regression test covering closed/finalized states and private-resource rejection.


## Coordinate-only participant release (historical revision)

- Participant-facing pages, public notebook and downloads do not recommend graph methods or GNNs. The public coordinate archives have exactly five numeric arrays: residue_type, residue_index, segment_index, pos, ca_mask. No precomputed edges are distributed; old intermediate archives were moved out of the served directory.
- Sample IDs, train/test split, labels and homology groups are unchanged: 26,961 samples / 20 classes; train 21,568, test 5,393.
- Baseline now uses 31 basic composition/shape features and Logistic Regression. Shipped Python and every notebook cell ran in a standalone extracted starter kit: H-group validation Macro F1 0.24240, ~1.4 seconds on this computer including full refit and 5,393 predictions. Timing is hardware-dependent.
- Full suite: 43 tests passed, including auditing every coordinate file and recomputed features, case-sensitive domain caching, masks/segments, public code-only baseline and event-gated datasets. Production API/web builds passed.
- Code-only ZIP is publicly available before/after the event; actual data, features, coordinate archives and full Starter Kit remain restricted to the configured competition window.

- Final coordinate baseline passed the real PostgreSQL disposable-database submission flow: Public Macro F1 0.19510193623817368; all production records remained untouched.
