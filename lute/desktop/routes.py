"""
Desktop-only pages: choosing the data folder (e.g. a OneDrive folder
shared between computers).
"""

import os
import threading
from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    flash,
    url_for,
)
from markupsafe import escape
from lute.desktop import datafolder, inuse

bp = Blueprint("desktop", __name__, url_prefix="/desktop")

# Same keys as lute.desktop.launcher (not imported, to keep this light).
DESKTOP_KEY = "LUTE_DESKTOP"
RESTART_KEY = "LUTE_RESTART_FUNC"


def _info():
    return current_app.config.get(DESKTOP_KEY)


def _restart_soon():
    "Restart via the launcher after the response is sent."
    threading.Timer(1.0, current_app.config[RESTART_KEY]).start()
    return render_template("datatransfer/restarting.html")


@bp.route("/datafolder", methods=["GET"])
def datafolder_index():
    "Show the current data folder, and choices."
    info = _info()
    if info is None:
        return render_template("desktop/datafolder.html", info=None)
    current = datafolder.describe(info["datapath"])
    current["conflicts"] = datafolder.conflict_copies(info["datapath"])
    return render_template(
        "desktop/datafolder.html",
        info=info,
        current=current,
        candidates=datafolder.find_candidates(),
        computer=datafolder.this_computer(),
    )


@bp.route("/datafolder/check", methods=["POST"])
def datafolder_check():
    "Compare a chosen folder's data with the current data."
    info = _info()
    if info is None:
        return redirect(url_for("desktop.datafolder_index"))
    folder = datafolder.clean_path(request.form.get("folder", ""))
    try:
        datapath, backuppath = datafolder.resolve_layout(folder)
    except datafolder.DataFolderError as e:
        flash(escape(str(e)), "error")
        return redirect(url_for("desktop.datafolder_index"))

    if os.path.normcase(datapath) == os.path.normcase(info["datapath"]):
        flash("That folder is already in use.", "notice")
        return redirect(url_for("desktop.datafolder_index"))

    return render_template(
        "desktop/datafolder_confirm.html",
        info=info,
        folder=folder,
        target_datapath=datapath,
        target_backuppath=backuppath,
        current=datafolder.describe(info["datapath"]),
        target=datafolder.describe(datapath),
        other=inuse.other_computer_active(datapath),
    )


@bp.route("/datafolder/apply", methods=["POST"])
def datafolder_apply():
    "Switch to the chosen folder, optionally copying current data there."
    info = _info()
    if info is None:
        return redirect(url_for("desktop.datafolder_index"))
    folder = datafolder.clean_path(request.form.get("folder", ""))
    mode = request.form.get("mode", "use")
    try:
        datapath, _ = datafolder.resolve_layout(folder)
        target = datafolder.describe(datapath)
        if mode == "use" and target.get("error"):
            raise datafolder.DataFolderError(target["error"])
        if mode == "copy":
            datafolder.copy_data_into(info["datapath"], datapath, "lute.db")
    except (datafolder.DataFolderError, OSError) as e:
        flash(f"Could not switch: {escape(str(e))}", "error")
        return redirect(url_for("desktop.datafolder_index"))

    settings = datafolder.load_settings(info["settings_file"])
    settings["data_folder"] = folder
    datafolder.save_settings(info["settings_file"], settings)
    return _restart_soon()


@bp.route("/datafolder/reset", methods=["POST"])
def datafolder_reset():
    "Go back to the local data folder on this computer."
    info = _info()
    if info is None:
        return redirect(url_for("desktop.datafolder_index"))
    settings = datafolder.load_settings(info["settings_file"])
    settings.pop("data_folder", None)
    datafolder.save_settings(info["settings_file"], settings)
    return _restart_soon()
