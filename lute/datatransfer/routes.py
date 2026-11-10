"""
Data import/export routes.
"""

import os
import glob
import threading
from datetime import datetime
from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    send_file,
    flash,
    url_for,
)
from markupsafe import escape
from werkzeug.utils import secure_filename
from lute.datatransfer import service

bp = Blueprint("datatransfer", __name__, url_prefix="/datatransfer")

# Set by the desktop launcher (extra_config), so the page can offer a
# one-click restart to finish an import.
RESTART_KEY = "LUTE_RESTART_FUNC"


def _env():
    return current_app.env_config


def _restart_func():
    return current_app.config.get(RESTART_KEY)


@bp.route("/index", methods=["GET"])
def index():
    "Import/export page."
    return render_template(
        "datatransfer/index.html",
        pending=service.pending_import_info(_env().datapath),
        can_restart=_restart_func() is not None,
        datapath=_env().datapath,
    )


@bp.route("/export", methods=["GET"])
def export():
    "Download a Docker-layout zip of all data."
    ac = _env()
    os.makedirs(ac.temppath, exist_ok=True)
    for old in glob.glob(os.path.join(ac.temppath, "lute_data_export_*.zip")):
        try:
            os.remove(old)
        except OSError:
            pass
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(ac.temppath, f"lute_data_export_{stamp}.zip")
    service.export_zip(ac.dbfilename, ac.datapath, out)
    return send_file(out, as_attachment=True, download_name=os.path.basename(out))


@bp.route("/import", methods=["POST"])
def import_data():
    "Stage an uploaded zip for import."
    ac = _env()
    f = request.files.get("datafile")
    if f is None or f.filename == "":
        flash("Please choose a zip file to import.", "notice")
        return redirect(url_for("datatransfer.index"))

    os.makedirs(ac.temppath, exist_ok=True)
    upload = os.path.join(ac.temppath, "upload_" + secure_filename(f.filename))
    f.save(upload)
    try:
        info = service.stage_import(upload, ac.datapath, ac.dbname, f.filename)
        flash(
            f"Ready to import {escape(info['source'])}: {info['languages']} languages, "
            f"{info['books']} books, {info['terms']} terms.  "
            "Restart Lute to finish the import.",
            "notice",
        )
    except service.DataTransferError as e:
        flash(f"Import failed: {escape(str(e))}", "error")
    finally:
        try:
            os.remove(upload)
        except OSError:
            pass
    return redirect(url_for("datatransfer.index"))


@bp.route("/cancel", methods=["POST"])
def cancel():
    "Discard a staged import."
    service.cancel_pending_import(_env().datapath)
    flash("Import cancelled.", "notice")
    return redirect(url_for("datatransfer.index"))


@bp.route("/restart", methods=["POST"])
def restart():
    "Ask the desktop launcher to restart Lute (applies the import)."
    func = _restart_func()
    if func is None:
        flash("Please stop and start Lute again to finish the import.", "notice")
        return redirect(url_for("datatransfer.index"))
    # Give the response time to reach the browser first.
    threading.Timer(1.0, func).start()
    return render_template("datatransfer/restarting.html")
