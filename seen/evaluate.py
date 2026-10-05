import json
import math
import statistics
import time
from .retrieval import Search


def metrics(rankings, targets):
    ranks = [next((n+1 for n, item in enumerate(items) if item == target), None) for items, target in zip(rankings, targets)]
    count = len(ranks)
    return {'Recall@1': sum(r == 1 for r in ranks)/count,
            'Recall@5': sum(r is not None and r <= 5 for r in ranks)/count,
            'MRR': sum(1/r if r else 0 for r in ranks)/count}


def evaluate(store, embedder, path):
    with open(path, encoding='utf-8') as f:
        queries = json.load(f)
    if not isinstance(queries, list) or not queries:
        raise ValueError('Evaluation needs a nonempty list of queries and target_event_id values.')
    for item in queries:
        if not isinstance(item.get('query'), str) or not store.get(item.get('target_event_id')):
            raise ValueError(f'Invalid query or missing target event: {item}')
    embedder.load()  # Never report a fallback as dense evaluation.
    if store.stats()['embedded_events'] != store.stats()['events']:
        raise ValueError('Run seen reindex first; all evaluation events must have embeddings.')
    search = Search(store, embedder)
    started = time.perf_counter()
    with store.lock:
        search.sync()
    index_sync_ms=(time.perf_counter()-started)*1000
    report={'queries':len(queries), 'cutoff':100, 'index_sync_ms':index_sync_ms, **store.stats(), 'methods':{}}
    for mode in ('lexical', 'dense', 'hybrid'):
        # Warm inference once; model initialization is not hidden inside one method's latency.
        search.query(queries[0]['query'], mode, 100)
        rankings, latencies = [], []
        for item in queries:
            result = search.query(item['query'], mode, 100)
            if result['warning']:
                raise RuntimeError(result['warning'])
            rankings.append([r['event_id'] for r in result['results']])
            latencies.append(result['latency_ms'])
        report['methods'][mode] = {**metrics(rankings, [q['target_event_id'] for q in queries]),
            'mean_latency_ms':statistics.mean(latencies), 'max_latency_ms':max(latencies),
            'median_latency_ms':statistics.median(latencies),
            'p95_latency_ms':sorted(latencies)[max(0, math.ceil(.95*len(latencies))-1)],
            'latencies_ms':latencies,
            'rankings':rankings}
    return report
