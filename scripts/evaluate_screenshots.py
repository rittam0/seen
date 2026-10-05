"""Fixed synthetic screenshots through real Windows OCR and local retrieval."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seen.capture import Capture, Window
from seen.demo import screenshot
from seen.embeddings import Embedder
from seen.evaluate import evaluate
from seen.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-data', required=True, help='Directory containing a prepared models/ cache')
    parser.add_argument('--output', default='evaluation/results.json')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This evaluation requires real Windows OCR; no fixture-text substitution is allowed.')
    fixture_path = Path(__file__).resolve().parents[1] / 'evaluation/fixtures.json'
    fixtures = json.loads(fixture_path.read_text())
    embedder = Embedder(Path(args.model_data).resolve())
    embedder.load()
    with tempfile.TemporaryDirectory(prefix='seen-evaluation-') as temporary:
        store = Store(temporary)
        store.controls(paused=False)
        worker = Capture(store, embedder)
        queries = []
        started = time.perf_counter()
        for number, item in enumerate(fixtures):
            image = screenshot(item['title'], item['text'], 'article')
            window = Window(1, 'fixture.exe', 'Synthetic capture fixture', (0, 0, 1100, 650))
            worker.frames.put((image, window, 1785542400 + number, store.settings()['generation']))
            worker.stop.set()
            worker.process()
            if store.stats()['events'] != number + 1:
                raise RuntimeError('Fixture ingestion failed')
            event = store.get(number + 1)
            if not event['ocr_status'].startswith('ok') or not event['extracted_text'].strip():
                raise RuntimeError('Real OCR did not produce searchable text')
            if not event['has_embedding']:
                raise RuntimeError('Real embedding was not persisted')
            queries.append({'query': item['query'], 'target_event_id': number + 1})
        indexing_seconds = time.perf_counter() - started
        query_path = store.root / 'queries.json'
        query_path.write_text(json.dumps(queries))
        report = evaluate(store, embedder, query_path)
        # Preserve only synthetic query labels, rankings, timings and aggregate sizes.
        report.update(corpus='24 generated synthetic screenshots, one pre-labelled target per query; not personal history',
                      ingestion='Capture.process -> native Windows OCR -> MiniLM -> JPEG/SQLite -> FAISS',
                      query_labels=queries, fixture_ids=[item['id'] for item in fixtures],
                      indexing_wall_seconds=indexing_seconds, model_startup_excluded=True,
                      latency_scope='warm in-process search; one pass per mode, p95 nearest-rank; excludes HTTP/UI',
                      python=platform.python_version(), platform=platform.platform(),
                      measured_at=datetime.now(timezone.utc).isoformat())
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k not in ('methods', 'query_labels', 'fixture_ids')}))
        for mode, result in report['methods'].items():
            print(mode, {k: v for k, v in result.items() if k not in ('rankings', 'latencies_ms')})


if __name__ == '__main__':
    main()
