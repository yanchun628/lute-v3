"PyInstaller entry point for the Windows desktop build."

import sys
from lute.desktop.launcher import main

if __name__ == "__main__":
    sys.exit(main())
