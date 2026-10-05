# Seen architecture

## Process boundaries

```text
Windows foreground window
   │ sample every 2 s; exclusion check before screen grab
   ▼
160×90 pixel change detector + application/window-title comparison
   │ changed frame only; focus checked again after grab
   ▼
Bounded queue (4 frames) ── full → drop new sample, retry next interval
   ▼
Index worker thread
   ├─ Windows OCR / optional Tesseract, 15 s timeout
   ├─ local MiniLM embedding (384 normalized float32 values)
   └─ generation check → JPEG + SQLite event + FTS trigger

Browser ── loopback FastAPI (separate process)
                    │
                    ├─ timeline / details / pause / exclusions / deletion
                    └─ query → calendar filter → BM25 and/or dense → rank → cards
                                                   │
                            SQLite FTS5       FAISS HNSW / filtered cosine
```

There is one capture process per data directory, enforced with a process file lock. The UI can run independently of capture. FastAPI's synchronous handlers execute in its thread pool. OCR/model inference never runs on the capture sampling thread or browser UI thread.

## Storage and recovery

`events` stores the required event ID, UTC epoch timestamp, executable name, window title, screenshot filename, full OCR text, and normalized text vector BLOB. `image_embedding` is nullable and unused. OCR status and per-event indexing milliseconds support diagnosis/evaluation. Screenshots use JPEG quality 85 at original capture resolution; thumbnail responses resize to fit 640×400. Event IDs are monotonic SQLite AUTOINCREMENT IDs.

SQLite uses WAL, an index on timestamps, and an external-content FTS5 index maintained by insertion/deletion triggers. FTS applies Porter stemming and Unicode tokenization. A cross-process history lock serializes commits, search-index updates, and deletion. Each connection has a bounded timeout and is closed promptly.

Images are written before database insertion and cleaned up if the insert fails. A hard crash between those operations can leave an unreferenced image; full history deletion also removes these. Vector insertion uses SQLite as the durable source; HNSW is synchronized lazily during unfiltered dense retrieval or eagerly by `reindex`/demo. Corrupt, deleted, or incomplete index files are recovered from stored vectors. Checkpoint writes use a temporary file and atomic replacement. Each search process reconciles indexed IDs against SQLite, so separately running capture and UI remain consistent. Query time never re-embeds historical events.

Privacy settings use a persisted generation counter. A queued frame records the generation under which it was captured. The indexing worker checks that generation before OCR and again under the history lock before saving. Pause, exclusion edits, and delete invalidate work already in progress. Delete pauses capture first, clears SQLite/FTS, removes screenshots and both index/checkpoint files, then checkpoints/vacuums SQLite. Search serializes against deletion, preventing deleted events from returning in a newly executed query.

## Retrieval

1. Interpret one supported time phrase as a half-open `[start, end)` local-calendar filter. Store/query timestamps use epoch seconds. Strip the recognized phrase from semantic/lexical query text.
2. Lexical: safely tokenize into at most 40 terms, omit a small English filler-word list, OR-match FTS5 terms, and use BM25 with title weight 3 and other fields weight 1. Normalize positive `-bm25` values by the highest lexical candidate value.
3. Dense: embed only the query with MiniLM. Unfiltered search uses FAISS `IndexIDMap2(IndexHNSWFlat)` with inner product, M=32, construction ef=100, search ef=64. Normalized vectors make inner product cosine similarity. Clamp negative cosine scores to zero.
4. Filtered dense search uses exact cosine over stored vectors in the calendar range. This avoids losing valid temporal results by first taking an unfiltered ANN top-k and then filtering it. It remains practical for thousands of events.
5. Hybrid: union the top 200 lexical and dense candidates; rank by `0.45 × normalized BM25 + 0.55 × nonnegative cosine`. Ties use descending event ID. Missing branches contribute zero. Displayed percentages express this relative score, not calibrated probability.
6. Blank or time-only recollections return chronological history in the selected interval. Dense model failure is explicit; hybrid falls back to lexical with a visible warning. No synthetic/hash vector fallback is used in production.

Document vectors combine application, window title, and OCR text. The fixed sentence model truncates long documents, a deliberate prototype limitation. Exact BM25 evidence and semantic similarity both help ordinary recollections, but visual appearance without supporting text and precise “before/after” relationships remain outside this baseline.

## Resource bounds

The queue holds four original-resolution images, plus active capture/indexing images. Model inference uses two CPU threads; FAISS also uses two. Reindex batches 16 documents. Persistent vector and SQLite data grow linearly with event count; screenshots dominate disk use over time. No automatic retention is imposed. Index synchronization currently reads stored vectors to reconcile the index, acceptable at the required several-thousand-event scale; a database change sequence would be a natural later optimization.

## Local service security

The server binds `127.0.0.1`. Host validation rejects DNS-rebinding hostnames; cross-site browser requests are rejected. A per-server random token from the same-origin status endpoint is required for mutations. No CORS grants are configured. CSP permits only local scripts/styles/images, blocks embedding, and all responses disable browser caching. Captured titles/text render via `textContent`, never injected HTML. Uvicorn query access logging is off. These protections do not defend against another process running as the same OS user.

## Dependencies

- [FastEmbed](https://qdrant.github.io/fastembed/): small CPU ONNX sentence embeddings, local cache.
- [FAISS](https://github.com/facebookresearch/faiss): persistent HNSW vector search.
- [SQLite FTS5](https://www.sqlite.org/fts5.html): local lexical retrieval.
- [PyWinRT](https://pywinrt.readthedocs.io/): Windows OCR bindings.
- MSS/Pillow/psutil/ctypes: screen capture, image processing, and foreground metadata.
- FastAPI/Uvicorn: a lightweight loopback API with static browser UI.

No image embeddings, learned personalization, clue-reliability models, contradiction handling, or research extensions are implemented.
