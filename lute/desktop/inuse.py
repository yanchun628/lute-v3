"""
"In use" marker for a data folder shared between computers.

While Lute runs, it keeps a small file in the data folder saying which
computer has it open, refreshed every minute.  Another computer that
sees a fresh marker (synced over by OneDrive) warns before opening the
same data, which would otherwise create sync conflicts.

The Docker version doesn't write or check this marker.
"""

import os
import json
import threading
import time
from datetime import datetime

from lute.desktop.datafolder import this_computer

MARKER = ".lute_in_use.json"
REFRESH_SECONDS = 60
STALE_SECONDS = 3 * REFRESH_SECONDS


def marker_path(datapath):
    "Marker file path."
    return os.path.join(datapath, MARKER)


def read_marker(datapath):
    "Marker dict, or None."
    try:
        with open(marker_path(datapath), encoding="utf-8") as f:
            ret = json.load(f)
        return ret if isinstance(ret, dict) else None
    except (OSError, ValueError):
        return None


def other_computer_active(datapath, now=None):
    """
    The marker dict if another computer has this data open (marker
    refreshed recently), else None.
    """
    m = read_marker(datapath)
    if m is None or m.get("computer", "").lower() == this_computer().lower():
        return None
    now = now if now is not None else time.time()
    age = now - float(m.get("heartbeat", 0))
    if age > STALE_SECONDS:
        return None
    m["age_seconds"] = max(0, int(age))
    return m


class InUseMarker:
    "Writes and refreshes the marker until stopped."

    def __init__(self, datapath):
        self.datapath = datapath
        self.started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._stop = threading.Event()
        self._thread = None

    def _write(self):
        data = {
            "computer": this_computer(),
            "pid": os.getpid(),
            "started": self.started,
            "heartbeat": time.time(),
        }
        tmp = marker_path(self.datapath) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, marker_path(self.datapath))
        except OSError:
            pass

    def _run(self):
        while not self._stop.wait(REFRESH_SECONDS):
            self._write()

    def start(self):
        "Write now, then refresh in the background."
        self._write()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        "Stop refreshing and remove the marker if it's ours."
        self._stop.set()
        m = read_marker(self.datapath)
        if m and m.get("computer") == this_computer() and m.get("pid") == os.getpid():
            try:
                os.remove(marker_path(self.datapath))
            except OSError:
                pass
