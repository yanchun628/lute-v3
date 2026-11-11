"""
Data folder choice tests.
"""

import os
import sqlite3
from contextlib import closing

import pytest

from lute.desktop import datafolder
from lute.desktop.datafolder import DataFolderError


@pytest.fixture(name="lute_db")
def fixture_lute_db(app, testconfig, tmp_path):
    "A copy of the test db."
    # pylint: disable=unused-argument
    dest = str(tmp_path / "source.db")
    with closing(sqlite3.connect(testconfig.dbfilename)) as src, closing(
        sqlite3.connect(dest)
    ) as dst:
        src.backup(dst)
    return dest


def _put_db(lute_db, folder):
    os.makedirs(folder, exist_ok=True)
    with closing(sqlite3.connect(lute_db)) as src, closing(
        sqlite3.connect(os.path.join(folder, "lute.db"))
    ) as dst:
        src.backup(dst)


def _theme(dbfile):
    with closing(sqlite3.connect(dbfile)) as conn:
        return conn.execute(
            "select StValue from settings where StKey='current_theme'"
        ).fetchone()[0]


def _set_theme(dbfile, v):
    with closing(sqlite3.connect(dbfile)) as conn:
        conn.execute("update settings set StValue=? where StKey='current_theme'", (v,))
        conn.commit()


def test_resolve_layout_docker_root(lute_db, tmp_path):
    "Docker folder: data/ and backups/ inside it."
    root = tmp_path / "my_lute_docker"
    _put_db(lute_db, str(root / "data"))
    (root / "docker-compose.yml").write_text("x")
    assert datafolder.resolve_layout(str(root)) == (
        str(root / "data"),
        str(root / "backups"),
    )


def test_resolve_layout_docker_data_folder(lute_db, tmp_path):
    "Choosing the data folder of a Docker layout puts backups beside it."
    root = tmp_path / "my_lute_docker"
    _put_db(lute_db, str(root / "data"))
    (root / "docker-compose.yml").write_text("x")
    assert datafolder.resolve_layout(f'"{root / "data"}"') == (
        str(root / "data"),
        str(root / "backups"),
    )


def test_resolve_layout_plain_and_empty(lute_db, tmp_path):
    "Plain folder with lute.db; empty folder gets Docker layout."
    plain = tmp_path / "plain"
    _put_db(lute_db, str(plain))
    assert datafolder.resolve_layout(str(plain)) == (
        str(plain),
        str(plain / "backups"),
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    assert datafolder.resolve_layout(str(empty)) == (
        str(empty / "data"),
        str(empty / "backups"),
    )
    with pytest.raises(DataFolderError, match="not found"):
        datafolder.resolve_layout(str(tmp_path / "missing"))


def test_settings_round_trip_and_bad_file(tmp_path):
    "Missing/bad settings file gives {}."
    f = str(tmp_path / "sub" / "desktop_settings.json")
    assert datafolder.load_settings(f) == {}
    datafolder.save_settings(f, {"data_folder": "C:\\x"})
    assert datafolder.load_settings(f) == {"data_folder": "C:\\x"}
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("not json")
    assert datafolder.load_settings(f) == {}


def test_describe(lute_db, tmp_path):
    "Counts and modified time, or has_db False."
    _put_db(lute_db, str(tmp_path / "d"))
    d = datafolder.describe(str(tmp_path / "d"))
    assert d["has_db"] is True
    assert set(d) >= {"languages", "books", "terms", "modified"}
    assert datafolder.describe(str(tmp_path / "nothing"))["has_db"] is False


def test_find_candidates(lute_db, tmp_path):
    "Docker roots and plain folders are found; deep/hidden ones skipped."
    root = tmp_path / "OneDrive"
    _put_db(lute_db, str(root / "my_lute_docker" / "data"))
    _put_db(lute_db, str(root / "Docs" / "lute_plain"))
    _put_db(lute_db, str(root / ".hidden" / "x"))
    _put_db(lute_db, str(root / "a" / "b" / "c" / "d" / "e"))
    found = datafolder.find_candidates([str(root)])
    assert str(root / "my_lute_docker") in found
    assert str(root / "Docs" / "lute_plain") in found
    assert len(found) == 2


def test_copy_data_into_empty_and_existing(lute_db, tmp_path):
    "Copy current data; existing data in dest is backed up first."
    src = tmp_path / "src"
    _put_db(lute_db, str(src))
    _set_theme(str(src / "lute.db"), "SOURCE")
    (src / "userimages" / "1").mkdir(parents=True)
    (src / "userimages" / "1" / "a.jpeg").write_text("img")

    dest = tmp_path / "dest"
    assert datafolder.copy_data_into(str(src), str(dest)) is None
    assert _theme(str(dest / "lute.db")) == "SOURCE"
    assert (dest / "userimages" / "1" / "a.jpeg").exists()
    assert (dest / "useraudio").is_dir()

    _set_theme(str(dest / "lute.db"), "OLD_DEST")
    bkp = datafolder.copy_data_into(str(src), str(dest))
    assert _theme(str(dest / "lute.db")) == "SOURCE"
    assert os.path.basename(bkp).startswith("before_copy_")
    assert _theme(os.path.join(bkp, "lute.db")) == "OLD_DEST"


def test_conflict_copies(tmp_path):
    "OneDrive conflict copies for this computer are found, not user files."
    for n in ["lute.db", "lute-backup.db", "lute-MYPC.db", "lute-mypc-2.db", "x.db"]:
        (tmp_path / n).write_text("x")
    assert datafolder.conflict_copies(str(tmp_path), "MyPC") == [
        "lute-MYPC.db",
        "lute-mypc-2.db",
    ]
