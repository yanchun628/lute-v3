# Lute3 for Windows (desktop build)

A normal Windows program for Lute: no Docker, Python or pip needed.

## For users

Two ways to get it:

* **Installer**: run `Lute3-<version>-setup.exe`. It installs for your user
  only, so no admin rights are needed, and adds a Start menu entry (plus a
  desktop shortcut if you pick that option).
* **Portable**: unzip `Lute3-<version>-portable.zip` anywhere and run
  `Lute3\Lute3.exe`.

When you start Lute, your browser opens to it and a Lute icon appears in
the system tray (bottom right; it may be hidden under the `^` arrow).
Right-click that icon to:

* **Open Lute**: opens it in your browser again (double-click does this too)
* **Open data folder**: shows your database, backups, images and logs
* **Quit Lute**: stops Lute

Starting Lute a second time just opens the browser, so you won't end up
with two copies running.

**Where your data lives**

| Version | Data folder |
|---|---|
| Installer | `%LOCALAPPDATA%\Lute3\Lute3`, the same folder the pip version uses, so existing pip users keep their data |
| Portable | `Lute3\data\` next to `Lute3.exe` (turned on by `portable.txt`) |

Uninstalling never deletes your data.

**Languages**: every space-delimited language works out of the box, and so
do Japanese (MeCab and the ipadic dictionary are bundled), Turkish and
Classical Chinese.

**Windows SmartScreen** may say "Windows protected your PC" because the exe
isn't code-signed. Click *More info* and then *Run anyway*.

**If Lute won't start**, look at `lute_desktop.log` in the data folder.

## For developers

Build from the repo root (Python 3.11 recommended):

```
powershell -ExecutionPolicy Bypass -File windows\build.ps1
```

This creates `.venv` if needed, installs dependencies, and writes to `dist\`:
the `Lute3\` folder, the portable zip, and the installer (the installer
needs [Inno Setup 6](https://jrsoftware.org/isinfo.php):
`winget install JRSoftware.InnoSetup`).

Use `-SkipDeps` to skip the pip installs and `-SkipInstall` to skip the
installer.

To try the launcher from source:

```
python -m lute.desktop.launcher --portable --no-tray
```

The GitHub workflow `.github/workflows/windows-desktop.yml` builds both
files on `windows-latest`. Run it manually from the Actions tab, or push a
`v*` tag to also attach them to a release.

| File | Purpose |
|---|---|
| `lute/desktop/launcher.py` | Tray launcher: data folder, MeCab setup, single instance, waitress server |
| `windows/lute3.spec` | PyInstaller spec, one-folder build |
| `windows/lute3.iss` | Inno Setup installer script |
| `windows/build.ps1` | One-command build |
