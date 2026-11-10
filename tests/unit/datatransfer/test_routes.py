"""
Data import/export route smoke tests.
"""

import io
import zipfile

import pytest

from lute.datatransfer import service


@pytest.fixture(name="no_pending")
def fixture_no_pending(testconfig):
    "Never leave a staged import behind for the next app startup."
    yield
    service.cancel_pending_import(testconfig.datapath)


def test_index_page(client):
    "Page renders, and is linked from the menu."
    response = client.get("/datatransfer/index")
    assert b"Import / Export data" in response.data
    assert b"/datatransfer/export" in response.data


def test_export_download(client):
    "Export returns a zip with the db."
    response = client.get("/datatransfer/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as zf:
        assert "lute_data_export/data/lute.db" in zf.namelist()
    response.close()


def test_import_bad_file_shows_error(client, no_pending):
    "Garbage upload is rejected."
    # pylint: disable=unused-argument
    data = {"datafile": (io.BytesIO(b"not a zip"), "bad.zip")}
    response = client.post(
        "/datatransfer/import",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Import failed" in response.data


def test_import_export_cancel_cycle(client, testconfig, no_pending):
    "Upload an export: import is staged; then cancel it."
    # pylint: disable=unused-argument
    exported = client.get("/datatransfer/export").data
    data = {"datafile": (io.BytesIO(exported), "export.zip")}
    response = client.post(
        "/datatransfer/import",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Ready to import export.zip" in response.data
    assert b"Stop and start Lute again" in response.data
    assert service.pending_import_info(testconfig.datapath) is not None

    response = client.post("/datatransfer/cancel", follow_redirects=True)
    assert b"Import cancelled" in response.data
    assert service.pending_import_info(testconfig.datapath) is None


def test_restart_without_launcher_asks_for_manual_restart(client):
    "Non-desktop installs can't restart themselves."
    response = client.post("/datatransfer/restart", follow_redirects=True)
    assert b"Please stop and start Lute again" in response.data
