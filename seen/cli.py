import argparse
import json
import logging
import signal
import time
from .config import data_path
from .storage import Store
from .embeddings import Embedder


def main():
    parser = argparse.ArgumentParser(description='Seen — local desktop memory')
    parser.add_argument('--data', help='Local data directory (default: ~/.seen or SEEN_DATA)')
    sub = parser.add_subparsers(dest='command', required=True)
    ui = sub.add_parser('ui', help='Open the local search server')
    ui.add_argument('--port', type=int, default=8765)
    capture = sub.add_parser('capture', help='Run the Windows capture worker')
    capture.add_argument('--interval', type=float, default=2)
    capture.add_argument('--start', action='store_true', help='Explicitly resume recording on launch')
    sub.add_parser('pause')
    sub.add_parser('resume')
    sub.add_parser('status')
    sub.add_parser('setup-model', help='Download the open-source model once (internet required)')
    sub.add_parser('reindex', help='Embed events that are missing vectors')
    demo = sub.add_parser('demo', help='Add clearly labeled synthetic sample moments')
    demo.add_argument('--lexical-only', action='store_true')
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('queries')
    evaluate.add_argument('--output', default='evaluation.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    root = data_path(args.data)
    store, embedder = Store(root), Embedder(root)
    if args.command == 'setup-model':
        embedder.load(download=True)
        print(f'Model ready in {root / "models"}. Runtime inference is offline.')
    elif args.command == 'ui':
        import uvicorn
        from .server import create_app
        print(f'Open http://127.0.0.1:{args.port} — capture starts separately.')
        uvicorn.run(create_app(root), host='127.0.0.1', port=args.port, access_log=False)
    elif args.command == 'capture':
        from .capture import Capture
        if not 1 <= args.interval <= 3:
            parser.error('--interval must be between 1 and 3 seconds')
        if args.start:
            store.controls(paused=False)
        worker = Capture(store, embedder, args.interval)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: worker.stop.set())
        worker.run()
    elif args.command in ('pause', 'resume'):
        print(json.dumps(store.controls(paused=args.command == 'pause'), indent=2))
    elif args.command == 'status':
        print(json.dumps({**store.settings(), **store.stats()}, indent=2))
    elif args.command == 'demo':
        from .demo import seed
        seed(store, None if args.lexical_only else embedder)
    elif args.command == 'reindex':
        from .retrieval import Search
        embedder.load()
        with store.lock:
            with store.connect() as db:
                rows = db.execute('SELECT * FROM events WHERE text_embedding IS NULL').fetchall()
            for offset in range(0, len(rows), 16):
                batch = rows[offset:offset+16]
                started = time.perf_counter()
                vectors = embedder.encode([f"{r['application']}\n{r['window_title']}\n{r['extracted_text']}" for r in batch])
                elapsed = (time.perf_counter()-started)*1000/len(batch)
                with store.connect() as db:
                    db.executemany('UPDATE events SET text_embedding=?,indexing_ms=indexing_ms+? WHERE event_id=?',
                                   [(v.tobytes(), elapsed, r['event_id']) for r, v in zip(batch, vectors)])
            Search(store, embedder).sync()
            store.set_state(model_error=None)
        print(f'Embedded {len(rows)} events; persistent index ready.')
    elif args.command == 'evaluate':
        from .evaluate import evaluate
        result = evaluate(store, embedder, args.queries)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
