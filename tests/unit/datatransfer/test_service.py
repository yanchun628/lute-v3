"""
Data import/export service tests.
"""

import os
import shutil
import sqlite3
import zipfile
from contextlib import closing

import pytest

from lute.datatransfer import service
from lute.datatransfer.service import DataTransferError


@pytest.fixture(name="lute_db")
def fixture_lute_db(app, testconfig, tmp_path):
    "A copy of the (demo) test db, outside of the test datapath."
    # pylint: disable=unused-argument
    dest = str(tmp_path / "source.db")
    with closing(sqlite3.connect(testconfig.dbfilename)) as src, closing(
        sqlite3.connect(dest)
    ) as dst:
        src.backup(dst)
    return dest


def _set_setting(dbfile, key, value):
    with closing(sqlite3.connect(dbfile)) as conn:
        conn.execute("update settings set StValue=? where StKey=?", (value, key))
        conn.commit()


def _get_setting(dbfile, key):
    with closing(sqlite3.connect(dbfile)) as conn:
        row = conn.execute("select StValue from settings where StKey=?", (key,))
        return row.fetchone()[0]


def _make_docker_zip(path, lute_db, root="my_lute_docker/"):
    "Zip with the same layout as a Docker data folder backup."
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{root}docker-compose.yml", "services: {}")
        zf.writestr(f"{root}backups/lute_backup_2026-01-01.db.gz", "x")
        zf.write(lute_db, f"{root}data/lute.db")
        zf.write(lute_db, f"{root}data/lute - old.db")
        zf.writestr(f"{root}data/userimages/1/apple.jpeg", "img")
        zf.writestr(f"{root}data/useraudio/", "")
        zf.writestr(f"{root}data/temp/junk.txt", "junk")
        zf.writestr(f"{root}data/.system_db_backups/old.db", "old")
    return str(path)


def test_find_data_root_variants():
    "Shortest path wins, then a parent folder named data."
    f = service._find_data_root  # pylint: disable=protected-access
    assert f(["lute.db"], "lute.db") == ""
    assert f(["data/lute.db", "data/userimages/"], "lute.db") == "data/"
    assert f(["x/data/lute.db", "x/data/old/lute.db"], "lute.db") == "x/data/"
    assert f(["a/lute.db", "data/lute.db"], "lute.db") == "data/"
    with pytest.raises(DataTransferError, match="No lute.db"):
        f(["data/other.db"], "lute.db")


def test_stage_docker_layout_zip(lute_db, tmp_path):
    "Only the db and user data folders are staged."
    z = _make_docker_zip(tmp_path / "docker.zip", lute_db)
    datapath = str(tmp_path / "datapath")
    info = service.stage_import(z, datapath, "lute.db", "docker.zip")

    assert info["source"] == "docker.zip"
    assert set(info) >= {"languages", "books", "terms", "source"}
    stage = service.pending_dir(datapath)
    assert os.path.exists(os.path.join(stage, "lute.db"))
    assert os.path.exists(os.path.join(stage, "userimages", "1", "apple.jpeg"))
    assert os.path.isdir(os.path.join(stage, "useraudio"))
    for absent in ["lute - old.db", "temp", ".system_db_backups", "backups"]:
        assert not os.path.exists(os.path.join(stage, absent)), absent
    assert service.pending_import_info(datapath)["books"] == info["books"]


def test_stage_bad_files_rejected_and_cleaned_up(lute_db, tmp_path):
    "Bad zips raise, and leave no staged import."
    datapath = str(tmp_path / "datapath")

    notzip = tmp_path / "notzip.zip"
    notzip.write_text("hello")
    with pytest.raises(DataTransferError, match="not a valid zip"):
        service.stage_import(str(notzip), datapath)

    nodb = tmp_path / "nodb.zip"
    with zipfile.ZipFile(nodb, "w") as zf:
        zf.writestr("data/readme.txt", "x")
    with pytest.raises(DataTransferError, match="No lute.db"):
        service.stage_import(str(nodb), datapath)

    other = tmp_path / "other.db"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("create table x (a)")
    otherzip = tmp_path / "other.zip"
    with zipfile.ZipFile(otherzip, "w") as zf:
        zf.write(other, "data/lute.db")
    with pytest.raises(DataTransferError, match="Not a Lute database"):
        service.stage_import(str(otherzip), datapath)

    with closing(sqlite3.connect(lute_db)) as conn:
        conn.execute("insert into _migrations values ('29990101_future.sql')")
        conn.commit()
    newer = _make_docker_zip(tmp_path / "newer.zip", lute_db)
    with pytest.raises(DataTransferError, match="newer version"):
        service.stage_import(newer, datapath)

    assert service.pending_import_info(datapath) is None
    assert not os.path.exists(service.pending_dir(datapath))


def test_zip_slip_rejected(lute_db, tmp_path):
    "Paths escaping the staging folder are refused."
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(lute_db, "data/lute.db")
        zf.writestr("data/userimages/../../../evil.txt", "evil")
    datapath = tmp_path / "datapath"
    with pytest.raises(DataTransferError, match="Unsafe path"):
        service.stage_import(str(z), str(datapath))
    assert not (tmp_path / "evil.txt").exists()


def _make_current_data(datapath, lute_db):
    "Existing install: db + an image."
    os.makedirs(os.path.join(datapath, "userimages"))
    shutil.copy(lute_db, os.path.join(datapath, "lute.db"))
    _set_setting(os.path.join(datapath, "lute.db"), "current_theme", "CURRENT")
    with open(
        os.path.join(datapath, "userimages", "old.txt"), "w", encoding="utf-8"
    ) as f:
        f.write("old")


def test_apply_pending_import(lute_db, tmp_path):
    "Data is swapped, old data backed up, docker backup_dir kept."
    datapath = str(tmp_path / "datapath")
    _make_current_data(datapath, lute_db)
    _set_setting(lute_db, "current_theme", "IMPORTED")
    _set_setting(lute_db, "backup_dir", "/lute_backup")
    z = _make_docker_zip(tmp_path / "docker.zip", lute_db)
    service.stage_import(z, datapath)

    bkp = service.apply_pending_import(datapath, "lute.db")

    newdb = os.path.join(datapath, "lute.db")
    assert _get_setting(newdb, "current_theme") == "IMPORTED"
    # Left as-is, so the db still works with Docker (resolved at runtime).
    assert _get_setting(newdb, "backup_dir") == "/lute_backup"
    assert os.path.exists(os.path.join(datapath, "userimages", "1", "apple.jpeg"))
    assert not os.path.exists(os.path.join(datapath, "userimages", "old.txt"))
    for d in service.DATA_SUBDIRS:
        assert os.path.isdir(os.path.join(datapath, d)), d

    assert os.path.basename(bkp).startswith("before_import_")
    assert _get_setting(os.path.join(bkp, "lute.db"), "current_theme") == "CURRENT"
    assert os.path.exists(os.path.join(bkp, "userimages", "old.txt"))
    assert service.pending_import_info(datapath) is None


def test_apply_without_pending_does_nothing(tmp_path):
    "No staged import, no change."
    assert service.apply_pending_import(str(tmp_path), "lute.db") is None


def test_failed_apply_restores_current_data(lute_db, tmp_path, monkeypatch):
    "Errors during the swap put the original data back."
    datapath = str(tmp_path / "datapath")
    _make_current_data(datapath, lute_db)
    service.stage_import(_make_docker_zip(tmp_path / "d.zip", lute_db), datapath)

    def _boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "check_lute_db", _boom)
    with pytest.raises(RuntimeError):
        service.apply_pending_import(datapath, "lute.db")

    restored = os.path.join(datapath, "lute.db")
    assert _get_setting(restored, "current_theme") == "CURRENT"
    assert os.path.exists(os.path.join(datapath, "userimages", "old.txt"))
    assert not os.path.exists(os.path.join(datapath, "userimages", "1"))


def test_export_has_docker_layout_and_round_trips(lute_db, tmp_path):
    "Export can be dropped into docker, and imported again."
    datapath = str(tmp_path / "datapath")
    _make_current_data(datapath, lute_db)
    os.makedirs(os.path.join(datapath, "temp"))
    with open(os.path.join(datapath, "temp", "junk.txt"), "w", encoding="utf-8") as f:
        f.write("junk")

    out = str(tmp_path / "export.zip")
    livedb = os.path.join(datapath, "lute.db")
    service.export_zip(livedb, datapath, out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        zf.extract("lute_data_export/data/lute.db", str(tmp_path / "x"))
    assert "lute_data_export/docker-compose.yml" in names
    assert "lute_data_export/backups/" in names
    assert "lute_data_export/data/userimages/old.txt" in names
    assert not any("temp" in n for n in names)
    exported_db = str(tmp_path / "x" / "lute_data_export" / "data" / "lute.db")
    assert _get_setting(exported_db, "backup_dir") == "/lute_backup"
    assert _get_setting(exported_db, "current_theme") == "CURRENT"
    assert _get_setting(livedb, "backup_dir") != "/lute_backup", "live db unchanged"

    other = str(tmp_path / "other_install")
    info = service.stage_import(out, other)
    assert "books" in info
