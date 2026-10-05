from datetime import datetime, timezone
import time
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from seen.capture import ChangeDetector, excluded, Capture, Window
from seen.storage import Store
from seen.retrieval import Search
from seen.temporal import interpret
from seen.server import create_app
from seen.evaluate import metrics


class FakeEmbedder:
    dimension = 4
    def load(self): return self
    def encode(self, texts):
        result=[]
        for text in texts:
            t=text.lower()
            v=np.array([any(w in t for w in ('database','repository','vector')), any(w in t for w in ('terminal','error','docker')), 'paper' in t, .1],dtype=np.float32)
            result.append(v/np.linalg.norm(v))
        return np.stack(result)


@pytest.fixture
def memory(tmp_path):
    store=Store(tmp_path)
    embed=FakeEmbedder()
    for text in ('vector database repository', 'terminal error docker', 'research paper'):
        name=text.split()[0]+'.jpg'
        Image.new('RGB',(80,60),'white').save(tmp_path/'screenshots'/name)
        store.add(time.time(), 'chrome.exe', text, name, text, embed.encode([text])[0].tobytes())
    return store, embed


@pytest.mark.parametrize('mode',['lexical','dense','hybrid'])
def test_retrieval(memory,mode):
    store,embed=memory
    assert Search(store,embed).query('database repository',mode)['results'][0]['event_id']==1


def test_fts_punctuation_and_injection(memory):
    store,embed=memory
    for q in ('" OR * )', 'database AND NOT', "'; DROP TABLE events; --", '😺'):
        Search(store,embed).query(q,'lexical')
    assert store.stats()['events']==3


def test_index_recovery_and_delete(memory):
    store,embed=memory
    search=Search(store,embed)
    search.query('database','dense')
    (store.root/'vectors.faiss').write_bytes(b'corrupt')
    assert Search(store,embed).query('database','dense')['results'][0]['event_id']==1
    store.add(time.time(),'code','docker','none.jpg','docker',embed.encode(['docker'])[0].tobytes())
    assert len(search.query('docker','dense')['results'])==4
    store.delete()
    assert search.query('database','hybrid')['results']==[]
    assert list((store.root/'screenshots').iterdir())==[]
    assert store.settings()['paused']


@pytest.mark.parametrize('phrase,start,end',[
    ('today','2026-09-09T00:00:00','2026-09-10T00:00:00'),
    ('yesterday','2026-09-08T00:00:00','2026-09-09T00:00:00'),
    ('this morning','2026-09-09T00:00:00','2026-09-09T12:00:00'),
    ('two days ago','2026-09-07T00:00:00','2026-09-08T00:00:00'),
    ('last week','2026-08-31T00:00:00','2026-09-07T00:00:00')])
def test_time(phrase,start,end):
    clean,bounds=interpret('database '+phrase,datetime(2026,9,9,15,tzinfo=timezone.utc))
    assert clean.strip()=='database'
    assert bounds==tuple(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() for t in (start,end))


def test_temporal_filter_all_methods(memory):
    store,embed=memory
    with store.connect() as db:
        db.execute('UPDATE events SET timestamp=?',(datetime(2026,9,9,12,tzinfo=timezone.utc).timestamp(),))
        db.execute('UPDATE events SET timestamp=? WHERE event_id=1',(datetime(2026,9,8,12,tzinfo=timezone.utc).timestamp(),))
    for mode in ('lexical','dense','hybrid'):
        result=Search(store,embed).query('database yesterday',mode,now=datetime(2026,9,9,15,tzinfo=timezone.utc))
        assert [r['event_id'] for r in result['results']]==[1]


def test_change_detection():
    detector=ChangeDetector()
    image=Image.new('RGB',(200,100),'white')
    assert detector.changed(image,'window')
    detector.accept(image,'window')
    assert not detector.changed(image,'window')
    slightly=image.copy();slightly.putpixel((0,0),(0,0,0))
    assert not detector.changed(slightly,'window')
    assert detector.changed(Image.new('RGB',(200,100),'black'),'window')
    assert detector.changed(image,'other window')


def test_exclusions():
    assert excluded('chrome.exe','Seen — Find your moments',[])
    assert excluded('chrome.exe','Seen - Search',[])
    assert excluded('Bitwarden.exe','Vault',['bitwarden.exe'])
    assert not excluded('chrome.exe','An article I have seen',[])


def test_generation_discards_queued_frame(memory,monkeypatch):
    store,embed=memory
    store.controls(paused=False)
    capture=Capture(store,embed)
    generation=store.settings()['generation']
    capture.frames.put((Image.new('RGB',(20,20)),Window(1,'code.exe','editor',(0,0,20,20)),time.time(),generation))
    store.controls(excluded_apps=['code.exe'])
    monkeypatch.setattr('seen.capture.ocr',lambda _:pytest.fail('Stale frame must never reach OCR'))
    capture.stop.set();capture.process()
    assert store.stats()['events']==3


def test_delete_during_ocr_cannot_resurrect_history(memory,monkeypatch):
    store,embed=memory
    store.controls(paused=False)
    capture=Capture(store,embed)
    capture.frames.put((Image.new('RGB',(20,20)),Window(1,'code.exe','editor',(0,0,20,20)),time.time(),store.settings()['generation']))
    def erase(_):
        store.delete()
        return 'private text','ok'
    monkeypatch.setattr('seen.capture.ocr',erase)
    capture.stop.set();capture.process()
    assert store.stats()['events']==0
    assert list((store.root/'screenshots').iterdir())==[]


def test_api_security_and_flow(memory):
    store,embed=memory
    with TestClient(create_app(store.root,embed)) as client:
        status=client.get('/api/status').json()
        assert client.post('/api/controls',json={'paused':False}).status_code==403
        assert client.get('/api/status',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert client.get('/api/status',headers={'Host':'evil.example'}).status_code==400
        headers={'X-Seen-Token':status['token']}
        assert client.post('/api/controls',json={'paused':False},headers=headers).json()['paused']==False
        assert client.get('/api/search?q=database').json()['results'][0]['event_id']==1
        assert client.get('/api/events/1/image').headers['content-type']=='image/jpeg'
        assert client.get('/api/events/1/thumbnail').status_code==200
        assert client.get('/api/events/999').status_code==404
        assert client.get('/api/search?mode=nope').status_code==422
        assert client.get('/api/history?offset=-1').status_code==400
        assert client.delete('/api/history',headers=headers).status_code==200
        assert client.get('/api/history').json()['results']==[]


def test_metrics():
    result=metrics([[2,1],[2],[4,3]], [1,9,4])
    assert result['Recall@1']==pytest.approx(1/3)
    assert result['Recall@5']==pytest.approx(2/3)
    assert result['MRR']==pytest.approx(.5)


def test_model_failure_is_explicit(memory):
    store,embed=memory
    def fail(_): raise RuntimeError('missing model')
    embed.encode=fail
    result=Search(store,embed).query('database','hybrid')
    assert result['warning']
    assert result['results'][0]['event_id']==1
    assert Search(store,embed).query('database','dense')['results']==[]
