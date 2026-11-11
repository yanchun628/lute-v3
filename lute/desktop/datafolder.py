"""
Choosing where the desktop version keeps its data.

The data folder can be any folder, e.g. one synced by OneDrive and
shared with other computers or with the Docker version.  Docker layout
is understood: choosing "my_lute_docker" (which holds data/ and
backups/) uses my_lute_docker/data for data and my_lute_docker/backups
for backups.

The choice is stored in a small json file on this computer only
(never in the shared folder), so each computer can use its own path to
the same synced folder.
"""

import os
import json
import glob
import shutil
import socket
import sqlite3
from contextlib import closing
from datetime import datetime

from lute.datatransfer.service import (
    DATA_SUBDIRS,
    DataTransferError,
    check_lute_db,
    move_current_data_to,
)

SETTINGS_FILENAME = "desktop_settings.json"
DBNAME = "lute.db"


class DataFolderError(Exception):
    "Invalid data folder."


# ----------------------------------------------------------------------
# Settings file


def load_settings(settings_file):
    "Settings dict, {} if missing or invalid."
    try:
        with open(settings_file, encoding="utf-8") as f:
            ret = json.load(f)
        return ret if isinstance(ret, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings_file, settings):
    "Write settings dict."
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


# ----------------------------------------------------------------------
# Layout


def clean_path(p):
    "Normalize a path typed or pasted by the user."
    p = (p or "").strip().strip('"').strip("'")
    return os.path.abspath(os.path.expandvars(os.path.expanduser(p)))


def resolve_layout(folder):
    """
    Return (datapath, backuppath) for a chosen folder.

    - folder/lute.db exists: folder is the data folder.  Backups go to
      a sibling "backups" folder if it's a Docker layout, else
      folder/backups.
    - otherwise Docker layout: folder/data and folder/backups (also
      used for a new, empty folder, so Docker can use it too).
    """
    folder = clean_path(folder)
    if not os.path.isdir(folder):
        raise DataFolderError(f"Folder not found: {folder}")

    if os.path.isfile(os.path.join(folder, DBNAME)):
        parent = os.path.dirname(folder)
        docker_parent = os.path.basename(folder).lower() == "data" and (
            os.path.exists(os.path.join(parent, "docker-compose.yml"))
            or os.path.isdir(os.path.join(parent, "backups"))
        )
        if docker_parent:
            return folder, os.path.join(parent, "backups")
        return folder, os.path.join(folder, "backups")

    return os.path.join(folder, "data"), os.path.join(folder, "backups")


def describe(datapath):
    """
    Summary of the Lute data in datapath, for comparing before a switch.
    """
    dbfile = os.path.join(datapath, DBNAME)
    ret = {"datapath": datapath, "has_db": os.path.isfile(dbfile)}
    if not ret["has_db"]:
        return ret
    ret["modified"] = datetime.fromtimestamp(os.path.getmtime(dbfile)).strftime(
        "%Y-%m-%d %H:%M"
    )
    try:
        ret.update(check_lute_db(dbfile))
    except DataTransferError as e:
        ret["error"] = str(e)
    return ret


# ----------------------------------------------------------------------
# Finding existing data in OneDrive


def cloud_roots():
    "Local folders of OneDrive accounts on this computer."
    roots = []
    for key in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        p = os.environ.get(key)
        if p and os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def find_candidates(roots=None, max_depth=3, max_dirs=4000):
    """
    Folders under roots that hold Lute data (Docker layout or plain).
    Returns the folder a user would pick (the Docker root if there is
    one).
    """
    found = []
    seen = 0
    for root in roots if roots is not None else cloud_roots():
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            seen += 1
            if seen > max_dirs:
                return found
            depth = dirpath.count(os.sep) - root_depth
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and depth < max_depth
            ]
            if DBNAME in filenames:
                parent = os.path.dirname(dirpath)
                pick = (
                    parent if os.path.basename(dirpath).lower() == "data" else dirpath
                )
                if pick not in found:
                    found.append(pick)
                dirnames[:] = []
    return found


# ----------------------------------------------------------------------
# Copy current data into a folder


def copy_data_into(src_datapath, dest_datapath, src_dbname=DBNAME):
    """
    Copy the current data into dest_datapath, as lute.db.

    Anything already in dest is first moved to
    dest/.system_db_backups/before_copy_<timestamp>/.  Uses sqlite's
    online backup, so the source db can be open.  Returns the backup
    folder (or None if dest was empty).
    """
    os.makedirs(dest_datapath, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bkp = os.path.join(dest_datapath, ".system_db_backups", f"before_copy_{stamp}")
    moved = move_current_data_to(dest_datapath, DBNAME, bkp)
    if not moved:
        shutil.rmtree(bkp, ignore_errors=True)
        bkp = None

    src_db = os.path.join(src_datapath, src_dbname)
    with closing(sqlite3.connect(src_db)) as src, closing(
        sqlite3.connect(os.path.join(dest_datapath, DBNAME))
    ) as dst:
        src.backup(dst)
    for d in DATA_SUBDIRS:
        s = os.path.join(src_datapath, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest_datapath, d), dirs_exist_ok=True)
        else:
            os.makedirs(os.path.join(dest_datapath, d), exist_ok=True)
    return bkp


# ----------------------------------------------------------------------
# Sync problems


def this_computer():
    "Name of this computer."
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def conflict_copies(datapath, computer=None):
    """
    OneDrive keeps both versions when a file changed on two computers,
    renaming one to e.g. "lute-DESKTOP1.db".  Returns such files found
    for this computer.
    """
    computer = (computer or this_computer()).lower()
    stem, ext = os.path.splitext(DBNAME)
    ret = []
    for f in glob.glob(os.path.join(datapath, f"{stem}-*{ext}")):
        name = os.path.basename(f).lower()
        if name.startswith(f"{stem}-{computer}"):
            ret.append(os.path.basename(f))
    return sorted(ret)
