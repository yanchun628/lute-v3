"""
"In use" marker tests.
"""

import json
import os
import time

from lute.desktop import inuse


def _write(datapath, **kw):
    with open(inuse.marker_path(str(datapath)), "w", encoding="utf-8") as f:
        json.dump(kw, f)


def test_no_marker_or_bad_marker(tmp_path):
    "Nothing open elsewhere."
    assert inuse.other_computer_active(str(tmp_path)) is None
    with open(inuse.marker_path(str(tmp_path)), "w", encoding="utf-8") as f:
        f.write("garbage")
    assert inuse.other_computer_active(str(tmp_path)) is None


def test_other_computer_fresh_and_stale(tmp_path, monkeypatch):
    "Fresh marker from another computer is reported; stale is ignored."
    monkeypatch.setattr(inuse, "this_computer", lambda: "HERE")
    now = time.time()
    _write(tmp_path, computer="THERE", heartbeat=now - 30, started="x")
    m = inuse.other_computer_active(str(tmp_path), now=now)
    assert m["computer"] == "THERE" and m["age_seconds"] == 30

    _write(tmp_path, computer="THERE", heartbeat=now - inuse.STALE_SECONDS - 1)
    assert inuse.other_computer_active(str(tmp_path), now=now) is None

    _write(tmp_path, computer="here", heartbeat=now)
    assert inuse.other_computer_active(str(tmp_path), now=now) is None


def test_marker_start_stop(tmp_path, monkeypatch):
    "Our marker is written, then removed; others' markers are kept."
    monkeypatch.setattr(inuse, "this_computer", lambda: "HERE")
    m = inuse.InUseMarker(str(tmp_path))
    m.start()
    data = inuse.read_marker(str(tmp_path))
    assert data["computer"] == "HERE" and data["pid"] == os.getpid()
    m.stop()
    assert inuse.read_marker(str(tmp_path)) is None

    _write(tmp_path, computer="THERE", pid=1, heartbeat=time.time())
    m2 = inuse.InUseMarker(str(tmp_path))
    m2.stop()
    assert inuse.read_marker(str(tmp_path))["computer"] == "THERE"
