"""
Import/export of a whole Lute data folder.

The exchange format is the folder layout used by the Docker version
(docker-compose maps ./data to /lute_data and ./backups to /lute_backup):

  <anything>/
    docker-compose.yml        (export only, for convenience)
    backups/                  (export only, empty)
    data/
      lute.db
      userimages/ useraudio/ userthemes/ plugins/

so an export can be dropped straight into a Docker setup that uses the
official image, and a zip of an existing Docker folder can be imported.

Importing replaces the current data, so it's done in two steps:

1. stage_import(): validate the zip and extract the needed files into
   <datapath>/import_pending/.  The running app is not touched.
2. apply_pending_import(): called at startup *before* the database is
   opened.  Backs up the current data, swaps in the staged data, and
   leaves machine-specific settings (paths) alone, as they are
   resolved at runtime.
"""

import os
import json
import shutil
import sqlite3
import zipfile
import tempfile
from contextlib import closing
from datetime import datetime

# Sub-folders of the data dir that are user data, and are transferred.
DATA_SUBDIRS = ["userimages", "useraudio", "userthemes", "plugins"]

PENDING_DIRNAME = "import_pending"
READY_MARKER = "READY.json"

# Docker's backup volume, see docker/docker-compose.yml.example.
DOCKER_BACKUP_DIR = "/lute_backup"

DOCKER_COMPOSE = """\
# Exported from Lute.  To use with Docker:
#   1. Stop your Lute container (docker compose stop).
#   2. Replace your existing "data" folder with the "data" folder here
#      (or run Lute from this folder).
#   3. docker compose up -d
# Change the left-hand port (5001) if you use a different one.
services:
  lute:
    image: jzohrab/lute3:latest
    ports:
      - 5001:5001
    volumes:
      - ./data:/lute_data
      - ./backups:/lute_backup
"""


class DataTransferError(Exception):
    "Raised for invalid import files and similar problems."


def _migrations_dir():
    "Folder of one-time schema migrations shipped with this Lute."
    thisdir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(thisdir, "..", "db", "schema", "migrations")


def _known_migrations():
    return {f for f in os.listdir(_migrations_dir()) if f.endswith(".sql")}


def check_lute_db(dbfile):
    """
    Raise DataTransferError if dbfile isn't a Lute db this version can use.

    Returns a dict of summary info (counts) for display.
    """
    try:
        with closing(sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "select name from sqlite_master where type='table'"
                )
            }
            needed = {"_migrations", "settings", "languages", "books", "words"}
            missing = needed - tables
            if missing:
                raise DataTransferError(
                    f"Not a Lute database (missing tables: {', '.join(sorted(missing))})."
                )
            applied = {
                os.path.basename(r[0])
                for r in conn.execute("select filename from _migrations")
            }
            info = {
                "languages": conn.execute("select count(*) from languages").fetchone()[
                    0
                ],
                "books": conn.execute("select count(*) from books").fetchone()[0],
                "terms": conn.execute("select count(*) from words").fetchone()[0],
            }
    except sqlite3.DatabaseError as e:
        raise DataTransferError(f"Not a valid database file: {e}") from e

    # Old migrations get folded into the baseline schema, so unknown
    # names are only a problem if they're dated after our newest one
    # (migration files are named yyyymmdd_...).
    known = _known_migrations()
    latest = max(known)
    newer = {m for m in applied - known if m > latest}
    if newer:
        raise DataTransferError(
            "This data comes from a newer version of Lute "
            f"(unknown migrations: {', '.join(sorted(newer))}).  "
            "Please upgrade this Lute first."
        )
    return info


def _find_data_root(names, dbname):
    """
    Find the folder prefix in the zip holding the database.

    Accepts e.g. "my_lute_docker/data/lute.db", "data/lute.db",
    "lute.db".  Prefers the shortest path, then a parent named "data".
    """
    cands = [n for n in names if n == dbname or n.endswith("/" + dbname)]
    if not cands:
        raise DataTransferError(f"No {dbname} found in the zip file.")

    def _rank(n):
        parts = n.split("/")
        in_data = len(parts) >= 2 and parts[-2] == "data"
        return (len(parts), 0 if in_data else 1)

    best = sorted(cands, key=_rank)[0]
    return best[: -len(dbname)]  # "" or "some/path/"


def _safe_target(destdir, relpath):
    "Return destdir/relpath, refusing paths that escape destdir (zip-slip)."
    dest_root = os.path.realpath(destdir)
    target = os.path.realpath(os.path.join(dest_root, relpath))
    if os.path.commonpath([dest_root, target]) != dest_root:
        raise DataTransferError(f"Unsafe path in zip file: {relpath}")
    return target


def pending_dir(datapath):
    "Staging folder for an import."
    return os.path.join(datapath, PENDING_DIRNAME)


def pending_import_info(datapath):
    "Info dict of a staged import, or None."
    marker = os.path.join(pending_dir(datapath), READY_MARKER)
    if not os.path.exists(marker):
        return None
    with open(marker, encoding="utf-8") as f:
        return json.load(f)


def cancel_pending_import(datapath):
    "Remove any staged import."
    shutil.rmtree(pending_dir(datapath), ignore_errors=True)


def _extract_data(zf, stage, dbname):
    "Extract the db (renamed to dbname) and user data folders to stage."
    names = [n.replace("\\", "/") for n in zf.namelist()]
    # Exports and Docker always use "lute.db"; this install may
    # use another DBNAME.  The staged copy gets the local name.
    src_dbname = dbname
    if not any(n == dbname or n.endswith("/" + dbname) for n in names):
        src_dbname = "lute.db"
    root = _find_data_root(names, src_dbname)
    wanted = [root + src_dbname] + [root + d + "/" for d in DATA_SUBDIRS]

    for info, name in zip(zf.infolist(), names):
        if not any(name == w or name.startswith(w) for w in wanted):
            continue
        rel = name[len(root) :]
        if rel == src_dbname:
            rel = dbname
        target = _safe_target(stage, rel)
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)


def stage_import(zip_path, datapath, dbname="lute.db", source_name=None):
    """
    Validate zip_path and extract its Lute data to the staging folder.

    Returns the info dict (counts, source).  Raises DataTransferError.
    """
    stage = pending_dir(datapath)
    cancel_pending_import(datapath)
    os.makedirs(stage)

    try:
        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as e:
            raise DataTransferError("The file is not a valid zip file.") from e
        with zf:
            _extract_data(zf, stage, dbname)

        result = check_lute_db(os.path.join(stage, dbname))
        result["source"] = source_name or os.path.basename(zip_path)
        result["staged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(stage, READY_MARKER), "w", encoding="utf-8") as f:
            json.dump(result, f)
        return result
    except Exception:
        cancel_pending_import(datapath)
        raise


def move_current_data_to(datapath, dbname, backup_dir):
    "Move the current db and data subdirs into backup_dir."
    os.makedirs(backup_dir)
    moved = []
    for name in [dbname] + DATA_SUBDIRS:
        src = os.path.join(datapath, name)
        if os.path.exists(src):
            shutil.move(src, os.path.join(backup_dir, name))
            moved.append(name)
    return moved


def apply_pending_import(datapath, dbname, output_func=None):
    """
    If an import is staged, swap it in.  Must be called before the db
    is opened.  Returns the before-import backup folder, or None if
    nothing was staged.

    The current data is moved (not deleted) to
    <datapath>/.system_db_backups/before_import_<timestamp>/.
    On any failure the current data is put back.
    """
    outfunc = output_func or (lambda s: None)
    info = pending_import_info(datapath)
    if info is None:
        return None

    stage = pending_dir(datapath)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(datapath, ".system_db_backups", f"before_import_{stamp}")
    outfunc(f"Importing data from {info.get('source')} ...")

    moved = move_current_data_to(datapath, dbname, backup_dir)
    try:
        for name in [dbname] + DATA_SUBDIRS:
            src = os.path.join(stage, name)
            dest = os.path.join(datapath, name)
            if os.path.exists(src):
                shutil.move(src, dest)
            elif name in DATA_SUBDIRS:
                os.makedirs(dest, exist_ok=True)
        # Settings holding paths from another machine (backup_dir,
        # mecab_path) are left alone: they're resolved at runtime, so
        # the db can still be used by e.g. Docker afterwards.
        check_lute_db(os.path.join(datapath, dbname))
    except Exception:
        # Roll back: remove partial import, restore the originals.
        for name in [dbname] + DATA_SUBDIRS:
            p = os.path.join(datapath, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)
        for name in moved:
            shutil.move(os.path.join(backup_dir, name), os.path.join(datapath, name))
        raise

    cancel_pending_import(datapath)
    outfunc(f"Import done.  Previous data saved in {backup_dir}")
    return backup_dir


def _add_dir_to_zip(zf, srcdir, arcdir):
    "Add srcdir recursively under arcdir."
    zf.writestr(arcdir.rstrip("/") + "/", "")
    for dirpath, _dirnames, filenames in os.walk(srcdir):
        rel = os.path.relpath(dirpath, srcdir)
        arcbase = arcdir if rel == "." else f"{arcdir}/{rel.replace(os.sep, '/')}"
        if rel != ".":
            zf.writestr(arcbase + "/", "")
        for fn in filenames:
            zf.write(os.path.join(dirpath, fn), f"{arcbase}/{fn}")


def export_zip(dbfile, datapath, out_zip, folder_name="lute_data_export"):
    """
    Write a Docker-layout zip of the current data to out_zip.

    Uses sqlite's online backup, so Lute can keep running.
    backup_dir in the exported db is set to Docker's /lute_backup.
    """
    with tempfile.TemporaryDirectory() as tmp:
        dbcopy = os.path.join(tmp, "lute.db")
        with closing(sqlite3.connect(dbfile)) as src, closing(
            sqlite3.connect(dbcopy)
        ) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(dbcopy)) as conn:
            conn.execute(
                "update settings set StValue=? where StKey='backup_dir'",
                (DOCKER_BACKUP_DIR,),
            )
            conn.commit()

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{folder_name}/docker-compose.yml", DOCKER_COMPOSE)
            zf.writestr(f"{folder_name}/backups/", "")
            zf.write(dbcopy, f"{folder_name}/data/lute.db")
            for d in DATA_SUBDIRS:
                src = os.path.join(datapath, d)
                if os.path.isdir(src):
                    _add_dir_to_zip(zf, src, f"{folder_name}/data/{d}")
    return out_zip
