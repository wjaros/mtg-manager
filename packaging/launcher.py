"""Entry point of the bundled app (PyInstaller): same CLI as `mtgdm`, window by default."""

import sys

from mtgdm.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
