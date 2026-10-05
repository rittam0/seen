import os
import threading
import numpy as np
from .config import MODEL, DIMENSION


class Embedder:
    dimension = DIMENSION

    def __init__(self, root):
        self.root = root
        self.model = None
        self.lock = threading.Lock()

    def load(self, download=False):
        with self.lock:
            if self.model is None:
                # Runtime cannot silently fetch a model or transmit captured text.
                if not download:
                    os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
                from fastembed import TextEmbedding
                self.model = TextEmbedding(MODEL, cache_dir=str(self.root / 'models'),
                                           local_files_only=not download, threads=2)
        return self

    def encode(self, texts):
        self.load()
        with self.lock:
            vectors = np.asarray(list(self.model.embed(texts, batch_size=16)), dtype=np.float32)
        vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        return vectors
