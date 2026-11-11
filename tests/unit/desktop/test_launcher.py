"""
Desktop launcher helper tests (no server started).
"""

import os

import yaml

from lute.desktop import launcher, datafolder


def test_write_config_default_and_managed(tmp_path):
    "Managed backup path only for a custom folder."
    f = launcher.write_config(str(tmp_path), "C:\\data")
    with open(f, encoding="utf-8") as fh:
        c = yaml.safe_load(fh)
    assert c["DATAPATH"] == "C:\\data"
    assert "BACKUP_PATH" not in c and "MANAGED_BACKUP_PATH" not in c

    f = launcher.write_config(str(tmp_path), "C:\\it's\\data", "C:\\it's\\backups")
    with open(f, encoding="utf-8") as fh:
        c = yaml.safe_load(fh)
    assert c["DATAPATH"] == "C:\\it's\\data"
    assert c["BACKUP_PATH"] == "C:\\it's\\backups"
    assert c["MANAGED_BACKUP_PATH"] is True


def test_choose_data_location(tmp_path, monkeypatch):
    "Default, chosen folder, and missing chosen folder."
    local = str(tmp_path / "local")
    os.makedirs(local)
    loc = launcher.choose_data_location(local)
    assert loc.datapath == local and not loc.is_custom

    shared = tmp_path / "OneDrive" / "my_lute_docker"
    shared.mkdir(parents=True)
    datafolder.save_settings(
        launcher.settings_file(local), {"data_folder": str(shared)}
    )
    loc = launcher.choose_data_location(local)
    assert loc.is_custom
    assert loc.datapath == str(shared / "data")
    assert loc.backuppath == str(shared / "backups")
    assert os.path.isdir(loc.datapath) and os.path.isdir(loc.backuppath)

    datafolder.save_settings(
        launcher.settings_file(local), {"data_folder": str(tmp_path / "gone")}
    )
    monkeypatch.setattr(launcher, "ask_yes_no", lambda msg: True)
    loc = launcher.choose_data_location(local)
    assert loc.datapath == local and not loc.is_custom
    monkeypatch.setattr(launcher, "ask_yes_no", lambda msg: False)
    assert launcher.choose_data_location(local) is None
