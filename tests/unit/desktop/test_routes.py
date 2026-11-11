"""
Data folder page and managed backup path tests.
"""

import os
import sqlite3
from contextlib import closing

import pytest

from lute.desktop import datafolder
from lute.desktop import routes as desktop_routes


@pytest.fixture(name="desktop_app")
def fixture_desktop_app(app, testconfig, tmp_path, monkeypatch):
    "App configured as if started by the desktop launcher."
    calls = []
    app.config["LUTE_DESKTOP"] = {
        "settings_file": str(tmp_path / "local" / "desktop_settings.json"),
        "local_dir": str(tmp_path / "local"),
        "chosen_folder": None,
        "datapath": testconfig.datapath,
        "backuppath": None,
    }
    app.config["LUTE_RESTART_FUNC"] = lambda: calls.append("restart")

    class _NowTimer:
        "Run the restart immediately instead of after a delay."

        def __init__(self, _delay, func):
            self.func = func

        def start(self):
            self.func()

    monkeypatch.setattr(desktop_routes.threading, "Timer", _NowTimer)
    app.restart_calls = calls
    yield app


def _shared_folder(testconfig, tmp_path):
    "A Docker-layout folder holding a copy of the test db."
    root = tmp_path / "OneDrive" / "my_lute_docker"
    (root / "data").mkdir(parents=True)
    (root / "docker-compose.yml").write_text("x")
    with closing(sqlite3.connect(testconfig.dbfilename)) as src, closing(
        sqlite3.connect(str(root / "data" / "lute.db"))
    ) as dst:
        src.backup(dst)
    return root


def test_page_not_available_outside_desktop(client):
    "Plain Lute (pip/docker) shows a note, and no menu link."
    response = client.get("/desktop/datafolder")
    assert b"only available in the Windows desktop version" in response.data
    assert b"desktop_datafolder" not in client.get("/").data


def test_page_shows_current_folder_and_menu_link(desktop_app, testconfig):
    "Current folder shown; menu has the link."
    client = desktop_app.test_client()
    response = client.get("/desktop/datafolder")
    assert testconfig.datapath.encode() in response.data
    assert b"desktop_datafolder" in response.data


def test_check_then_use_folder_data(desktop_app, testconfig, tmp_path):
    "Compare page, then 'use' saves the choice and restarts."
    root = _shared_folder(testconfig, tmp_path)
    client = desktop_app.test_client()

    response = client.post("/desktop/datafolder/check", data={"folder": str(root)})
    assert b"Use the data in the new folder" in response.data
    assert str(root / "data").encode() in response.data

    response = client.post(
        "/desktop/datafolder/apply", data={"folder": str(root), "mode": "use"}
    )
    assert b"Restarting Lute" in response.data
    assert desktop_app.restart_calls == ["restart"]
    settings_file = desktop_app.config["LUTE_DESKTOP"]["settings_file"]
    assert datafolder.load_settings(settings_file)["data_folder"] == str(root)


def test_copy_current_data_into_empty_folder(desktop_app, tmp_path):
    "'copy' puts the current db into the new folder."
    root = tmp_path / "OneDrive" / "new_lute"
    root.mkdir(parents=True)
    client = desktop_app.test_client()
    response = client.post("/desktop/datafolder/check", data={"folder": str(root)})
    assert b"No Lute data yet" in response.data
    assert b"Use the data in the new folder" not in response.data

    client.post("/desktop/datafolder/apply", data={"folder": str(root), "mode": "copy"})
    assert os.path.exists(root / "data" / "lute.db")
    assert desktop_app.restart_calls == ["restart"]


def test_check_missing_folder(desktop_app, tmp_path):
    "Bad path is reported."
    client = desktop_app.test_client()
    response = client.post(
        "/desktop/datafolder/check",
        data={"folder": str(tmp_path / "nope")},
        follow_redirects=True,
    )
    assert b"Folder not found" in response.data


def test_reset_to_local(desktop_app):
    "Reset removes the choice and restarts."
    settings_file = desktop_app.config["LUTE_DESKTOP"]["settings_file"]
    datafolder.save_settings(settings_file, {"data_folder": "C:\\x", "other": 1})
    desktop_app.test_client().post("/desktop/datafolder/reset")
    assert datafolder.load_settings(settings_file) == {"other": 1}
    assert desktop_app.restart_calls == ["restart"]


def test_managed_backup_dir_is_used_and_not_overwritten(app, client, tmp_path):
    "Shared data folder: Docker's stored /lute_backup is kept."
    # pylint: disable=import-outside-toplevel
    from lute.db import db
    from lute.models.repositories import UserSettingRepository

    managed = tmp_path / "shared_backups"
    managed.mkdir()
    app.env_config.backup_path_managed = True
    app.env_config.default_user_backup_path = str(managed)
    try:
        with app.app_context():
            repo = UserSettingRepository(db.session)
            repo.set_value("backup_dir", "/lute_backup")
            db.session.commit()
            assert repo.get_backup_settings().backup_dir == str(managed)

        page = client.get("/settings/index").data
        assert str(managed).encode() in page
        assert b"readonly" in page

        with app.app_context():
            assert UserSettingRepository(db.session).get_value("backup_dir") == (
                "/lute_backup"
            )
    finally:
        app.env_config.backup_path_managed = False
