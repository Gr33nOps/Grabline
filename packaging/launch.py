"""PyInstaller entry point for Grabline Desktop.

The one binary plays three roles:
- the GUI app (default);
- the Native Messaging host, when a browser launches it with ``--native-host``
  (via the launcher script the pairing step writes);
- a one-shot ``--register-host`` mode the installer runs to register the host
  and stage the extension, then exit.
"""

import contextlib
import sys

if "--native-host" in sys.argv:
    from app.native_host.__main__ import main as host_main

    if __name__ == "__main__":
        raise SystemExit(host_main())
elif "--register-host" in sys.argv:
    from app.core import browser_setup
    from app.native_host.install import install as register_host

    def _register() -> int:
        register_host()
        with contextlib.suppress(OSError):
            browser_setup.install_extension_files()
        return 0

    if __name__ == "__main__":
        raise SystemExit(_register())
else:
    from app.__main__ import main

    if __name__ == "__main__":
        raise SystemExit(main())
