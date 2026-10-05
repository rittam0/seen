# Verification — 5 October 2026

The existing implementation was found in a local workspace without Git history;
application code was preserved. The public repository contains source and synthetic
fixtures only. It excludes prepared models, local databases, logs and personal screenshots.

## Tests and runtime

- Windows/Python 3.12.14: 21 existing tests passed with `SEEN_TEST_MODEL` pointing to
  an already prepared local model. Scope: BM25/dense/hybrid ranking, time filtering,
  query safety, deduplication, exclusions, privacy-generation invalidation, deletion,
  index recovery, API controls, screenshots and real Windows OCR/model integration.
- `python -m pip check`: no broken requirements in the existing environment.
- A three-second native capture run in isolated temporary storage retained one real
  foreground screenshot, persisted its metadata/image and returned it through history.
  That private temporary history was deleted; no pixels, title or OCR text were published.
- Browser search returned the expected synthetic screenshot. The result detail and direct
  moment link opened the full stored screenshot and extracted text successfully.
- CI installs the package, compiles source and runs tests on Linux and Windows.
  CI does not download model weights: the real-model integration test is optional.

## Fixed screenshot evaluation

Command: `python scripts/evaluate_screenshots.py --model-data <prepared-data-directory>`.
Inputs: `evaluation/fixtures.json`. Raw results: `evaluation/results.json`.

All 24 targets and queries were specified before executing searches. The corpus is
constructed and small; it is not a sample of the user's actual desktop history.
Each image was rendered, processed by native Windows OCR, embedded by actual local
MiniLM, and persisted as JPEG/SQLite before retrieval. Window titles were generic
fixture labels, so the searchable subject came from real OCR rather than injected text.

| Method | Recall@1 | Recall@5 | MRR@100 | Median ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| BM25 | 23/24 | 24/24 | 0.9792 | 2.63 | 3.71 |
| Dense | 24/24 | 24/24 | 1.0000 | 27.96 | 32.49 |
| Hybrid | 23/24 | 24/24 | 0.9792 | 31.92 | 36.66 |

History/index size: 929,784 bytes, excluding the shared model cache. Corpus ingestion
wall time: 2.218 seconds after model load. These are run-specific observations, not
capture throughput estimates. Each mode warmed once and ran one pass; search latency
excludes model startup, HTTP and UI. p95 is the nearest-rank sample statistic.

Dense outperformed hybrid at rank one in this corpus. No query, model or hybrid
weight was changed in response. No image embeddings or original-location reopening
are claimed. Source path/URL provenance is absent; screenshot reopening works.
