import os
from pathlib import Path

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384


def data_path(value=None):
    path = Path(value or os.environ.get("SEEN_DATA", Path.home() / ".seen")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
