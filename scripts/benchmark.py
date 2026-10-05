"""Measure retrieval at scale, with real vectors encoded once per fixture text.

This is a throughput smoke test on repeated synthetic content, not a quality benchmark.
Run: python scripts/benchmark.py --model-data demo-data --events 5000
"""
import argparse
import json
from pathlib import Path
import statistics
import tempfile
import time
from seen.demo import MOMENTS
from seen.storage import Store
from seen.embeddings import Embedder
from seen.retrieval import Search


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-data',default='demo-data')
    parser.add_argument('--events',type=int,default=5000)
    parser.add_argument('--output',default='benchmark.json')
    args=parser.parse_args()
    embed=Embedder(Path(args.model_data).resolve())
    texts=[f'{app} {title} {text}' for app,title,text,_,_ in MOMENTS]
    vectors=embed.encode(texts)
    with tempfile.TemporaryDirectory(prefix='seen-benchmark-') as root:
        store=Store(root)
        started=time.perf_counter()
        # Batch DB writes model the index size without generating fake screenshot files.
        with store.connect() as db:
            db.executemany('INSERT INTO events(timestamp,application,window_title,screenshot_path,extracted_text,text_embedding,indexing_ms,ocr_status) VALUES(?,?,?,?,?,?,?,?)',
                [(time.time()-i*2,MOMENTS[i%6][0],MOMENTS[i%6][1],'synthetic.jpg',texts[i%6],vectors[i%6].tobytes(),0,'synthetic') for i in range(args.events)])
        search=Search(store,embed)
        with store.lock:search.sync()
        report={'events':args.events,'build_ms':(time.perf_counter()-started)*1000,'fixture':'Six real model vectors repeated; screenshots omitted','methods':{}}
        for mode in ('lexical','dense','hybrid'):
            search.query('vector database repository',mode)
            times=[search.query(MOMENTS[i%6][3],mode)['latency_ms'] for i in range(18)]
            report['methods'][mode]={'median_ms':statistics.median(times),'p95_ms':sorted(times)[int(.95*(len(times)-1))],'max_ms':max(times)}
        report.update(store.stats())
        Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
