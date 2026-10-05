"""Synthetic, labeled fixtures. Never presented as real desktop history."""
import json
import textwrap
import time
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from .retrieval import Search

MOMENTS = [
 ('chrome.exe', 'GitHub · Qdrant / vector database', 'Qdrant is a vector similarity search engine. A repository for semantic search, embeddings and vector databases. The architecture diagram shows collections, shards, and the HNSW index.', 'vector database repository', 'repo'),
 ('WindowsTerminal.exe', 'Docker build · connection refused', 'ERROR: failed to solve: failed to fetch anonymous token. Connection refused on port 5432. docker compose up --build. Check the DATABASE_URL before editing the Dockerfile.', 'terminal error before editing Dockerfile', 'terminal'),
 ('chrome.exe', 'Designing a retrieval system', 'A blue architecture diagram: documents flow into a chunker, embedding model, vector index, and retrieval service. Hybrid search combines BM25 with semantic similarity.', 'article with blue architecture diagram', 'diagram'),
 ('msedge.exe', 'Long-context language models · research notes', 'Research paper: Lost in the Middle. Evaluating how language models use long contexts. Relevant information in the middle is harder to retrieve. Opened after a discussion about long-context models.', 'paper about long context models', 'paper'),
 ('Code.exe', 'Dockerfile · local-memory', 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD [python, app.py]', 'python container Dockerfile', 'code'),
 ('chrome.exe', 'A quieter way to work', 'Keep fewer tabs open. Make room for deep work with a focused morning routine. Write down one thing that matters and begin there.', 'article about focused morning routine', 'article'),
]


def font(size, mono=False):
    candidates = ['C:/Windows/Fonts/consola.ttf'] if mono else ['C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def screenshot(title, text, kind):
    dark = kind in ('terminal', 'code')
    image = Image.new('RGB', (1100, 650), '#192329' if dark else '#fafbf9')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1100, 48), fill='#263239' if dark else '#e8ede8')
    for x, color in zip((24, 46, 68), ('#cf897e', '#d8bc78', '#88a483')):
        draw.ellipse((x, 18, x+9, 27), fill=color)
    draw.text((100, 13), title, font=font(17), fill='#adbabf' if dark else '#647566')
    draw.text((48, 90), title, font=font(32), fill='#d9e5df' if dark else '#304a3a')
    if kind == 'diagram':
        labels = ['Documents', 'Embeddings', 'Vector index']
        for n, label in enumerate(labels):
            x = 60+n*350
            draw.rounded_rectangle((x, 190, x+265, 310), radius=12, fill='#e1ebf5', outline='#8ca9c5', width=2)
            draw.text((x+25, 230), label, font=font(25), fill='#4b7397')
            if n < 2:
                draw.line((x+268, 250, x+340, 250), fill='#7299bb', width=3)
                draw.polygon([(x+340,250),(x+330,244),(x+330,256)], fill='#7299bb')
        y=375
    else:
        y=165
    lines=[]
    for line in text.splitlines():
        lines.extend(textwrap.wrap(line, 79))
    for line in lines[:10]:
        draw.text((50, y), line, font=font(22, dark), fill='#a6c8b0' if dark else '#788878')
        y+=37
    draw.rectangle((0, 602, 1100, 650), fill='#27372e' if dark else '#eaf0e5')
    draw.text((25, 614), 'SEEN / SYNTHETIC DEMO — not a real captured screen', font=font(16), fill='#8b9b85')
    return image


def seed(store, embedder):
    started = time.perf_counter()
    docs = [f'{app}\n{title}\n{text}' for app, title, text, _, _ in MOMENTS]
    vectors = embedder.encode(docs) if embedder else [None]*len(docs)
    elapsed = (time.perf_counter()-started)*1000/len(docs)
    now = datetime.now().astimezone()
    queries=[]
    with store.lock:
        if store.stats()['events']:
            raise RuntimeError('Demo needs an empty data directory; use --data demo-data.')
        for n, ((app, title, text, query, kind), vector) in enumerate(zip(MOMENTS, vectors)):
            path = f'demo-{n}.jpg'
            screenshot(title, text, kind).save(store.root / 'screenshots' / path, quality=90)
            timestamp = (now - timedelta(hours=n*2+1)).timestamp()
            if kind == 'terminal':
                timestamp = (now-timedelta(days=1)).replace(hour=15, minute=12).timestamp()
            event_id = store.add(timestamp, app, f'[Demo] {title}', path, text,
                                 vector.tobytes() if vector is not None else None, elapsed, 'synthetic fixture text')
            queries.append(dict(query=query, target_event_id=event_id))
        if embedder:
            Search(store, embedder).sync()
    target = store.root / 'demo-queries.json'
    target.write_text(json.dumps(queries, indent=2), encoding='utf-8')
    print(f'Added {len(MOMENTS)} synthetic moments. Evaluation queries: {target}')
