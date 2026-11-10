"""
Desktop launcher: runs Lute as a normal Windows program.

- No console window; a tray icon gives "Open Lute" and "Quit".
- Starts the server on 127.0.0.1 and opens the default browser.
- Only one copy runs at a time: starting it again just opens the browser.
- Data location:
  - Portable mode (a file named "portable.txt" next to Lute3.exe):
    "data" folder next to Lute3.exe, so the whole folder can be moved
    or put on a USB stick.
  - Installed mode: the same per-user folder that the pip version uses
    (PlatformDirs user_data_dir, e.g. %LOCALAPPDATA%\\Lute3\\Lute3),
    so existing pip-installed users keep their data.
- Japanese: if libmecab.dll and the ipadic dictionary are bundled,
  MeCab is configured automatically.

Can also be run from source for testing:

  python -m lute.desktop.launcher [--portable] [--no-browser]
"""

import os
import sys
import argparse
import ctypes
import logging
import socket
import subprocess
import threading
import time
import traceback
import urllib.request
import webbrowser

from platformdirs import PlatformDirs

APP_NAME = "Lute3"
MUTEX_NAME = "Local\\Lute3DesktopSingleInstance"
DEFAULT_PORT = 5001
ERROR_ALREADY_EXISTS = 183

log = logging.getLogger("lute.desktop")

# Set when the web UI asks for a restart (e.g. to finish a data import).
RESTART_REQUESTED = threading.Event()


# ----------------------------------------------------------------------
# Paths


def is_frozen():
    "True if running from a PyInstaller bundle."
    return getattr(sys, "frozen", False)


def app_dir():
    "Folder holding Lute3.exe (or the repo root when run from source)."
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def bundle_dir():
    "Folder holding bundled resources (PyInstaller _internal dir)."
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return None


def is_portable(force=False):
    "Portable mode if forced, or if portable.txt is next to the exe."
    return force or os.path.exists(os.path.join(app_dir(), "portable.txt"))


def data_dir(portable):
    "Where the database, images, backups etc. live."
    if portable:
        return os.path.join(app_dir(), "data")
    return PlatformDirs(APP_NAME, APP_NAME).user_data_dir


def _yaml_path(p):
    "Quote a windows path for yaml."
    return "'" + p.replace("'", "''") + "'"


def write_config(datapath):
    """
    Write the launcher-managed config file and return its path.

    It's rewritten on every start so that the portable folder can be
    moved without breaking DATAPATH.
    """
    config_file = os.path.join(datapath, "desktop_config.yml")
    content = "\n".join(
        [
            "# Written by the Lute desktop launcher on every start.",
            "# Changes here will be overwritten.",
            "ENV: prod",
            "DBNAME: lute.db",
            f"DATAPATH: {_yaml_path(datapath)}",
            "",
        ]
    )
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(content)
    return config_file


def configure_mecab(datapath):
    """
    Point natto-py / MeCab at the bundled dll and dictionary, if present.

    Returns True if the bundled MeCab was found.
    """
    root = bundle_dir()
    if root is None:
        # From source: use the pip packages if installed.
        try:
            import MeCab as mecab_pkg  # pylint: disable=import-outside-toplevel
            import ipadic  # pylint: disable=import-outside-toplevel

            dll = os.path.join(os.path.dirname(mecab_pkg.__file__), "libmecab.dll")
            dicdir = ipadic.DICDIR
        except ImportError:
            return False
    else:
        dll = os.path.join(root, "MeCab", "libmecab.dll")
        dicdir = os.path.join(root, "ipadic", "dicdir")

    if not (os.path.exists(dll) and os.path.isdir(dicdir)):
        return False

    mecabrc = os.path.join(datapath, "mecabrc")
    with open(mecabrc, "w", encoding="utf-8") as f:
        f.write(f"dicdir = {dicdir}\n")

    os.environ["MECABRC"] = mecabrc
    os.environ["MECAB_CHARSET"] = "utf-8"
    # Read by lute.db.management._revised_mecab_path; Lute then stores
    # it as the mecab_path setting, which sets MECAB_PATH for natto.
    os.environ["LUTE_BUNDLED_MECAB_PATH"] = dll
    os.environ["MECAB_PATH"] = dll
    return True


# ----------------------------------------------------------------------
# Single instance, ports


def acquire_single_instance():
    "Returns a mutex handle, or None if another instance is running."
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def release_single_instance(handle):
    "Release the mutex so a restarted instance can take it."
    if os.name == "nt" and handle not in (None, True):
        ctypes.windll.kernel32.CloseHandle(handle)


def port_is_free(port):
    "True if nothing is listening on 127.0.0.1:port."
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port(preferred):
    "Preferred port if free, else any free port."
    if port_is_free(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_file(datapath):
    "File recording the port of the running instance."
    return os.path.join(datapath, "desktop_port.txt")


def wait_until_up(url, timeout=60):
    "Poll url until it answers."
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:  # pylint: disable=broad-exception-caught
            time.sleep(0.3)
    return False


# ----------------------------------------------------------------------
# UI helpers


def message_box(text, title="Lute", error=False):
    "Show a native message box (no-op off Windows)."
    if os.name != "nt":
        print(f"{title}: {text}")
        return
    flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def open_folder(path):
    "Open a folder in Explorer."
    if os.name == "nt":
        os.startfile(path)  # pylint: disable=no-member


def redirect_output(datapath):
    """
    Windowed exes have no stdout/stderr; send them to a log file.
    """
    logfile = os.path.join(datapath, "lute_desktop.log")
    stream = open(  # pylint: disable=consider-using-with
        logfile, "w", encoding="utf-8", buffering=1
    )
    sys.stdout = stream
    sys.stderr = stream
    sys.__stdout__ = stream
    sys.__stderr__ = stream
    logging.basicConfig(
        stream=stream,
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return logfile


# ----------------------------------------------------------------------
# Server


class LuteServer:
    "Lute flask app served by waitress in a background thread."

    def __init__(self, config_file, port):
        self.config_file = config_file
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        "Create the app and start serving."
        # pylint: disable=import-outside-toplevel
        from waitress.server import create_server
        from lute.app_factory import create_app, data_initialization
        from lute.db import db
        from lute.datatransfer.routes import RESTART_KEY

        extra = {RESTART_KEY: RESTART_REQUESTED.set}
        app = create_app(self.config_file, extra_config=extra, output_func=print)
        with app.app_context():
            data_initialization(db.session, print)

        self.server = create_server(app, host="127.0.0.1", port=self.port)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.server.run()
        except Exception:  # pylint: disable=broad-exception-caught
            # close() during shutdown raises inside run(); ignore.
            log.info("server stopped")

    def stop(self):
        "Stop serving."
        if self.server is not None:
            self.server.close()

    @property
    def url(self):
        "Home url."
        return f"http://127.0.0.1:{self.port}/"


def run_tray(server, datapath):
    "Show the tray icon; blocks until Quit."
    # pylint: disable=import-outside-toplevel
    import pystray
    from PIL import Image

    icon_path = None
    root = bundle_dir() or os.path.join(app_dir(), "lute")
    for cand in [
        os.path.join(root, "lute", "static", "favicon.ico"),
        os.path.join(root, "static", "favicon.ico"),
    ]:
        if os.path.exists(cand):
            icon_path = cand
            break
    image = Image.open(icon_path) if icon_path else Image.new("RGB", (32, 32))

    def on_open(_icon, _item):
        webbrowser.open(server.url)

    def on_data(_icon, _item):
        open_folder(datapath)

    def on_quit(icon, _item):
        icon.visible = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Lute", on_open, default=True),
        pystray.MenuItem("Open data folder", on_data),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Lute", on_quit),
    )
    icon = pystray.Icon("Lute3", image, f"Lute (port {server.port})", menu)

    def _stop_on_restart():
        RESTART_REQUESTED.wait()
        icon.visible = False
        icon.stop()

    threading.Thread(target=_stop_on_restart, daemon=True).start()
    icon.run()


# ----------------------------------------------------------------------
# Main


def _parse_args(argv):
    "Command line args."
    parser = argparse.ArgumentParser(description="Lute desktop launcher.")
    parser.add_argument("--portable", action="store_true", help="Force portable.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="Run until Ctrl-C.")
    return parser.parse_args(argv)


def _show_running_instance(datapath):
    "Another instance is running: open its page in the browser."
    try:
        with open(port_file(datapath), encoding="utf-8") as f:
            port = int(f.read().strip())
        webbrowser.open(f"http://127.0.0.1:{port}/")
    except (OSError, ValueError):
        message_box("Lute is already running (see the tray icon).")


def _start_server(args, datapath, portable):
    "Configure, start the server, and record its port."
    config_file = write_config(datapath)
    has_mecab = configure_mecab(datapath)
    port = choose_port(args.port)
    print(f"Lute desktop: data={datapath} portable={portable}")
    print(f"Lute desktop: port={port} bundled_mecab={has_mecab}")

    server = LuteServer(config_file, port)
    server.start()
    with open(port_file(datapath), "w", encoding="utf-8") as f:
        f.write(str(port))
    return server


def _wait_for_quit(args, server, datapath):
    "Open the browser, then block until the user quits."
    if not args.no_browser and wait_until_up(server.url):
        webbrowser.open(server.url)

    if args.no_tray:
        print(f"Running at {server.url}, Ctrl-C to stop.")
        while not RESTART_REQUESTED.is_set():
            time.sleep(0.5)
    else:
        run_tray(server, datapath)


def main(argv=None):
    "Entry point."
    args = _parse_args(argv)
    portable = is_portable(args.portable)
    datapath = data_dir(portable)
    os.makedirs(datapath, exist_ok=True)

    mutex = acquire_single_instance()
    if mutex is None:
        _show_running_instance(datapath)
        return 0

    logfile = redirect_output(datapath) if is_frozen() else None

    server = None
    try:
        server = _start_server(args, datapath, portable)
        _wait_for_quit(args, server, datapath)
    except KeyboardInterrupt:
        pass
    except Exception:  # pylint: disable=broad-exception-caught
        tb = traceback.format_exc()
        print(tb)
        where = f"\n\nDetails were written to:\n{logfile}" if logfile else ""
        message_box(f"Lute could not start.\n\n{tb[-800:]}{where}", error=True)
        return 1
    finally:
        if server is not None:
            server.stop()
        try:
            os.remove(port_file(datapath))
        except OSError:
            pass

    if RESTART_REQUESTED.is_set():
        release_single_instance(mutex)
        _spawn_restart(args, server)
    return 0


def _spawn_restart(args, server):
    "Start a new copy of Lute on the same port (the open page reloads)."
    if is_frozen():
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, "-m", "lute.desktop.launcher"]
    port = server.port if server is not None else args.port
    cmd += ["--port", str(port), "--no-browser"]
    if args.portable:
        cmd.append("--portable")
    if args.no_tray:
        cmd.append("--no-tray")
    print(f"Restarting: {cmd}")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # pylint: disable=consider-using-with
        cmd, cwd=app_dir(), creationflags=flags, close_fds=True
    )


if __name__ == "__main__":
    sys.exit(main())
