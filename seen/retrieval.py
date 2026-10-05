import re
import time
import numpy as np
import faiss
from .temporal import interpret
from .storage import public

faiss.omp_set_num_threads(2)
STOP = set('that the a an i saw had before after opened reading about with of for to in on it something was my'.split())


class Search:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder
        self.index = None
        self.generation = None

    def sync(self):
        """Caller holds history lock. SQLite is authoritative; crash recovery needs no ML."""
        generation = self.store.settings()['generation']
        if self.index is None or generation != self.generation:
            self.index = None
            path = self.store.root / 'vectors.faiss'
            if path.exists():
                try:
                    self.index = faiss.read_index(str(path))
                except RuntimeError:
                    pass
            self.generation = generation
        with self.store.connect() as db:
            rows = db.execute("SELECT event_id,text_embedding FROM events WHERE text_embedding IS NOT NULL ORDER BY event_id").fetchall()
        ids = {r['event_id'] for r in rows}
        existing = set(faiss.vector_to_array(self.index.id_map).tolist()) if self.index is not None else set()
        changed = False
        if self.index is None or not existing.issubset(ids):
            base = faiss.IndexHNSWFlat(self.embedder.dimension, 32, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efConstruction = 100
            base.hnsw.efSearch = 64
            self.index = faiss.IndexIDMap2(base)
            existing = set()
            changed = True
        missing = [r for r in rows if r['event_id'] not in existing]
        if missing:
            vectors = np.stack([np.frombuffer(r['text_embedding'], dtype=np.float32) for r in missing])
            self.index.add_with_ids(vectors, np.array([r['event_id'] for r in missing], dtype=np.int64))
            changed = True
        if changed:
            temp = self.store.root / 'vectors.tmp'
            faiss.write_index(self.index, str(temp))
            temp.replace(self.store.root / 'vectors.faiss')

    def query(self, query, mode='hybrid', limit=30, now=None):
        started = time.perf_counter()
        clean, bounds = interpret(query, now)
        tokens = [t for t in re.findall(r'\w+', clean.lower()) if t not in STOP][:40]
        warning = None
        vector = None
        if tokens and mode != 'lexical':
            try:
                vector = self.embedder.encode([clean])[0]
            except Exception:
                warning = "Semantic model unavailable. Run seen setup-model and seen reindex."
        with self.store.lock:
            if not tokens:
                results = self.store.history(limit=limit, bounds=bounds)
                for row in results:
                    row.update(score=0, lexical_score=0, dense_score=0)
            else:
                lex, dense = {}, {}
                clause = ' AND e.timestamp>=? AND e.timestamp<?' if bounds else ''
                with self.store.connect() as db:
                    if mode != 'dense':
                        match = ' OR '.join('"' + t + '"' for t in tokens)
                        rows = db.execute('''SELECT e.event_id, bm25(event_fts,1,3,1) AS rank FROM event_fts
                          JOIN events e ON e.event_id=event_fts.rowid WHERE event_fts MATCH ?''' + clause + ' ORDER BY rank LIMIT 200', [match] + (list(bounds) if bounds else [])).fetchall()
                        maximum = max([-r['rank'] for r in rows], default=1)
                        lex = {r['event_id']: -r['rank'] / maximum for r in rows}
                    if vector is not None:
                        if bounds:
                            # Exact cosine over the filtered subset avoids losing temporal matches
                            # when the global ANN top-k falls outside the requested date range.
                            rows = db.execute('SELECT event_id,text_embedding FROM events e WHERE text_embedding IS NOT NULL' + clause, bounds).fetchall()
                            if rows:
                                matrix = np.stack([np.frombuffer(r['text_embedding'], dtype=np.float32) for r in rows])
                                scores = matrix @ vector
                                top = np.argsort(-scores)[:200]
                                dense = {rows[i]['event_id']: float(max(0, scores[i])) for i in top}
                        else:
                            self.sync()
                            if self.index.ntotal:
                                scores, ids = self.index.search(vector.reshape(1, -1), min(200, self.index.ntotal))
                                dense = {int(i): float(max(0, s)) for i, s in zip(ids[0], scores[0]) if i >= 0}
                    candidates = set(lex) | set(dense)
                    def score(i):
                        if mode == 'lexical' or (warning and mode == 'hybrid'):
                            return lex.get(i, 0)
                        if mode == 'dense':
                            return dense.get(i, 0)
                        return .45 * lex.get(i, 0) + .55 * dense.get(i, 0)
                    ranked = sorted(candidates, key=lambda i: (-score(i), -i))[:limit]
                    results = []
                    for i in ranked:
                        if score(i) <= 0:
                            continue
                        row = public(db.execute('SELECT * FROM events WHERE event_id=?', (i,)).fetchone())
                        row.update(score=round(score(i), 4), lexical_score=round(lex.get(i, 0), 4), dense_score=round(dense.get(i, 0), 4))
                        results.append(row)
        return dict(results=results, latency_ms=round((time.perf_counter()-started)*1000, 2),
                    mode=mode, warning=warning, time_filter=list(bounds) if bounds else None)
