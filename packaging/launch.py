"""PyInstaller entry point for Grabline Desktop.

The one binary plays two roles: the GUI app, and — when a browser launches
it with ``--native-host`` (via the launcher script the pairing step writes) —
the Native Messaging host speaking framed JSON on stdio.
"""

import sys

if "--native-host" in sys.argv:
    from app.native_host.__main__ import main as host_main

    if __name__ == "__main__":
        raise SystemExit(host_main())
else:
    from app.__main__ import main

    if __name__ == "__main__":
        raise SystemExit(main())
