"""Windows foreground-only capture. No screenshot is taken for excluded windows."""
import ctypes
from ctypes import wintypes
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import psutil
from PIL import Image
from filelock import FileLock, Timeout

log = logging.getLogger(__name__)


@dataclass
class Window:
    handle: int
    application: str
    title: str
    rect: tuple


def excluded(application, title, exclusions):
    title = title.casefold().strip()
    # The browser tab title is controlled by Seen; reserve the prefix for all its views.
    return application.casefold() in ('seen.exe', 'lockapp.exe', 'logonui.exe', 'credentialuibroker.exe') or title == 'seen' or title.startswith('seen —') or title.startswith('seen -') or any(
        term.casefold().strip() in application.casefold() for term in exclusions if term.strip())


def foreground():
    if os.name != 'nt':
        raise RuntimeError('Desktop capture currently supports Windows only.')
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    handle = user.GetForegroundWindow()
    if not handle:
        return None
    text = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(handle) + 1)
    user.GetWindowTextW(handle, text, len(text))
    if not text.value.strip():
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    try:
        application = psutil.Process(pid.value).name()
    except (psutil.Error, OSError):
        return None  # Fail closed if the process cannot be identified.
    rect = wintypes.RECT()
    if not user.GetWindowRect(handle, ctypes.byref(rect)):
        return None
    return Window(handle, application, text.value, (rect.left, rect.top, rect.right, rect.bottom))


class ChangeDetector:
    def __init__(self, threshold=.025):
        self.threshold, self.previous, self.key = threshold, None, None

    def sample(self, image):
        return np.asarray(image.convert('RGB').resize((160, 90)), dtype=np.float32) / 255

    def changed(self, image, key):
        sample = self.sample(image)
        return self.previous is None or self.key != key or float(np.abs(sample - self.previous).mean()) >= self.threshold

    def accept(self, image, key):
        self.previous, self.key = self.sample(image), key


def ocr(image):
    if os.name == 'nt' and not os.environ.get('SEEN_TESSERACT'):
        try:
            from .windows_ocr import windows_ocr
            return windows_ocr(image), 'ok: Windows OCR'
        except Exception:
            log.debug('Windows OCR unavailable; trying Tesseract', exc_info=True)
    import pytesseract
    executable = os.environ.get('SEEN_TESSERACT') or shutil.which('tesseract')
    if not executable:
        default = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tesseract-OCR/tesseract.exe'
        executable = str(default) if default.exists() else None
    if not executable:
        return '', 'unavailable: install Tesseract for screen text'
    pytesseract.pytesseract.tesseract_cmd = executable
    try:
        return pytesseract.image_to_string(image, config='--psm 3', timeout=15).strip(), 'ok'
    except Exception as error:
        return '', f'error: {type(error).__name__}'


class Capture:
    def __init__(self, store, embedder, interval=2):
        self.store, self.embedder, self.interval = store, embedder, interval
        self.stop = threading.Event()
        self.frames = queue.Queue(maxsize=4)
        self.detector = ChangeDetector()
        self.dropped = 0

    def process(self):
        while not self.stop.is_set() or not self.frames.empty():
            try:
                image, window, timestamp, generation = self.frames.get(timeout=.3)
            except queue.Empty:
                continue
            try:
                settings = self.store.settings()
                if settings['paused'] or settings['generation'] != generation:
                    continue
                started = time.perf_counter()
                text, status = ocr(image)
                vector = None
                try:
                    vector = self.embedder.encode([f'{window.application}\n{window.title}\n{text}'])[0].tobytes()
                except Exception:
                    self.store.set_state(model_error='Semantic model unavailable; run seen setup-model, then seen reindex.')
                with self.store.lock:
                    settings = self.store.settings()
                    if settings['paused'] or settings['generation'] != generation or excluded(window.application, window.title, settings['excluded_apps']):
                        continue
                    filename = f'{uuid.uuid4().hex}.jpg'
                    path = self.store.root / 'screenshots' / filename
                    try:
                        image.save(path, quality=85)
                        self.store.add(timestamp, window.application, window.title, filename, text, vector,
                                       (time.perf_counter()-started)*1000, status)
                    except Exception:
                        path.unlink(missing_ok=True)
                        raise
                    self.store.set_state(last_capture=timestamp, ocr_status=status, capture_error=None)
            except Exception as error:
                log.exception('Indexing frame failed')
                self.store.set_state(capture_error=f'Indexing failed: {type(error).__name__}')
            finally:
                self.frames.task_done()

    def run(self):
        if os.name != 'nt':
            raise RuntimeError('Capture requires Windows. Search and demo work on other platforms.')
        import mss
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            ctypes.windll.kernel32.SetConsoleTitleW('Seen — Capture worker')
        except OSError:
            pass
        singleton = FileLock(str(self.store.root / 'capture.lock'), timeout=0)
        try:
            singleton.acquire()
        except Timeout:
            raise RuntimeError('Another capture worker is already running for this data directory.')
        worker = threading.Thread(target=self.process, name='seen-indexer')
        worker.start()
        try:
            with mss.mss() as screen:
                while not self.stop.is_set():
                    settings = self.store.settings()
                    self.store.set_state(worker_heartbeat=time.time(), interval=self.interval, queued=self.frames.qsize(), dropped=self.dropped)
                    if settings['paused']:
                        self.detector = ChangeDetector()
                    else:
                        try:
                            window = foreground()
                            if window and not excluded(window.application, window.title, settings['excluded_apps']):
                                left, top, right, bottom = window.rect
                                monitor = screen.monitors[0]
                                left, top = max(left, monitor['left']), max(top, monitor['top'])
                                right = min(right, monitor['left'] + monitor['width'])
                                bottom = min(bottom, monitor['top'] + monitor['height'])
                                if right > left and bottom > top:
                                    shot = screen.grab(dict(left=left, top=top, width=right-left, height=bottom-top))
                                    current = foreground()
                                    # Discard races when focus changes during capture.
                                    if current == window:
                                        image = Image.frombytes('RGB', shot.size, shot.rgb)
                                        key = (window.application, window.title)
                                        if self.detector.changed(image, key):
                                            try:
                                                self.frames.put_nowait((image, window, time.time(), settings['generation']))
                                                self.detector.accept(image, key)
                                            except queue.Full:
                                                self.dropped += 1
                        except Exception as error:
                            self.store.set_state(capture_error=f'Capture failed: {type(error).__name__}')
                            log.exception('Capture failed')
                    self.stop.wait(self.interval)
        finally:
            self.stop.set()
            worker.join()
            self.store.set_state(worker_heartbeat=0, queued=0)
            singleton.release()
