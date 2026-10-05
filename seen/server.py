import io
import secrets
import time
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import data_path
from .storage import Store
from .embeddings import Embedder
from .retrieval import Search


class Controls(BaseModel):
    paused: bool | None = None
    excluded_apps: list[str] | None = Field(default=None, max_length=100)


def create_app(root=None, embedder=None):
    store = Store(data_path(root))
    search = Search(store, embedder or Embedder(store.root))
    app = FastAPI(title='Seen', docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    token = secrets.token_urlsafe(32)
    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=static), name='static')
    app.state.store, app.state.search = store, search

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Cross-site access is disabled'}, status_code=403)
        if request.method not in ('GET', 'HEAD') and request.headers.get('x-seen-token') != token:
            return JSONResponse({'detail': 'Missing local session token'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/')
    def home():
        return FileResponse(static / 'index.html')

    @app.get('/moments/{event_id}')
    def moment_page(event_id: int):
        # Keep Seen's reserved window title even when opening the full moment in a new tab.
        return FileResponse(static / 'index.html')

    @app.get('/api/status')
    def status():
        settings = store.settings()
        return dict(**settings, **store.stats(), worker_online=time.time()-settings.get('worker_heartbeat', 0)<10,
                    data_directory=str(store.root), token=token)

    @app.post('/api/controls')
    def controls(values: Controls):
        data = values.model_dump(exclude_none=True)
        if 'excluded_apps' in data:
            data['excluded_apps'] = sorted(set(s.strip().lower()[:200] for s in data['excluded_apps'] if s.strip()))
        return store.controls(**data)

    @app.delete('/api/history')
    def delete_history():
        store.delete()
        return {'deleted': True, 'paused': True}

    @app.get('/api/search')
    def query(q: str = '', mode: Literal['lexical', 'dense', 'hybrid'] = 'hybrid', limit: int = 30):
        if len(q) > 1000 or not 1 <= limit <= 100:
            raise HTTPException(400, 'Query or limit is too large')
        return search.query(q, mode, limit)

    @app.get('/api/history')
    def history(limit: int = 30, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(400, 'Invalid pagination')
        return {'results': store.history(limit, offset)}

    @app.get('/api/events/{event_id}')
    def event(event_id: int):
        row = store.get(event_id)
        if not row:
            raise HTTPException(404, 'Moment not found')
        return row

    def image_bytes(event_id, thumbnail=False):
        with store.lock:
            row = event(event_id)
            path = store.root / 'screenshots' / row['screenshot_path']
            if not path.is_file():
                raise HTTPException(404, 'Screenshot not found')
            if not thumbnail:
                return Response(path.read_bytes(), media_type='image/jpeg')
            with Image.open(path) as image:
                image.thumbnail((640, 400))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=75)
            return Response(output.getvalue(), media_type='image/jpeg')

    @app.get('/api/events/{event_id}/image')
    def full_image(event_id: int):
        return image_bytes(event_id)

    @app.get('/api/events/{event_id}/thumbnail')
    def thumbnail(event_id: int):
        return image_bytes(event_id, True)

    return app
