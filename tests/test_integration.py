"""Optional real OCR/model check. Run with SEEN_TEST_MODEL pointing to a prepared data dir."""
import os
from pathlib import Path
import time
import threading
import pytest
from seen.capture import Capture, Window, foreground
from seen.demo import screenshot
from seen.embeddings import Embedder
from seen.retrieval import Search
from seen.storage import Store


@pytest.mark.skipif(os.name!='nt' or not os.environ.get('SEEN_TEST_MODEL'), reason='Requires Windows OCR and a prepared local model')
def test_real_ocr_to_semantic_result(tmp_path):
    embed=Embedder(Path(os.environ['SEEN_TEST_MODEL']).resolve())
    store=Store(tmp_path)
    store.controls(paused=False)
    worker=Capture(store,embed)
    image=screenshot('Vector database research','A repository about vector database architecture and semantic retrieval.','paper')
    worker.frames.put((image,Window(1,'fixture.exe','Vector database research',(0,0,1100,650)),time.time(),store.settings()['generation']))
    worker.stop.set();worker.process()
    result=Search(store,embed).query('repository for similarity search','dense')
    assert result['results']
    event=result['results'][0]
    assert 'vector' in event['extracted_text'].lower()
    assert event['ocr_status'].startswith('ok')
    assert (tmp_path/'screenshots'/event['screenshot_path']).is_file()
    assert event['has_embedding']


@pytest.mark.skipif(os.name!='nt',reason='Windows only')
def test_foreground_api_does_not_raise():
    window=foreground()
    assert window is None or (window.application and len(window.rect)==4)


@pytest.mark.skipif(os.name!='nt',reason='Windows only')
def test_paused_native_worker_starts_and_shuts_down(tmp_path,monkeypatch):
    # Native MSS initialization only: paused mode must never read a window or screen.
    store=Store(tmp_path)
    worker=Capture(store,None,interval=.05)
    monkeypatch.setattr('seen.capture.foreground',lambda:pytest.fail('Paused capture read foreground'))
    timer=threading.Timer(.15,worker.stop.set)
    timer.start()
    try:worker.run()
    finally:timer.join()
    assert store.stats()['events']==0
    assert store.settings()['worker_heartbeat']==0
