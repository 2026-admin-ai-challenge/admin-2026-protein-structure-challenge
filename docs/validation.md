# Validation record — 2026-10-01

The current release is documented under “Coordinate-only participant release” below. Earlier sections preserve intermediate and superseded validation records.

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


## Coordinate-only participant release (current)

- Participant-facing pages, public notebook and downloads do not recommend graph methods or GNNs. The public coordinate archives have exactly five numeric arrays: residue_type, residue_index, segment_index, pos, ca_mask. No precomputed edges are distributed; old intermediate archives were moved out of the served directory.
- Sample IDs, train/test split, labels and homology groups are unchanged: 26,961 samples / 20 classes; train 21,568, test 5,393.
- Baseline now uses 31 basic composition/shape features and Logistic Regression. Shipped Python and every notebook cell ran in a standalone extracted starter kit: H-group validation Macro F1 0.24240, ~1.4 seconds on this computer including full refit and 5,393 predictions. Timing is hardware-dependent.
- Full suite: 43 tests passed, including auditing every coordinate file and recomputed features, case-sensitive domain caching, masks/segments, public code-only baseline and event-gated datasets. Production API/web builds passed.
- Code-only ZIP is publicly available before/after the event; actual data, features, coordinate archives and full Starter Kit remain restricted to the configured competition window.

- Final coordinate baseline passed the real PostgreSQL disposable-database submission flow: Public Macro F1 0.19510193623817368; all production records remained untouched.
