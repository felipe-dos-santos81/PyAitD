# SPDX-License-Identifier: GPL-2.0-only
"""`python -m PyAitD` entry point; the shell lives in PyAitD.app.shell."""
from PyAitD.app.shell import main

if __name__ == "__main__":
    raise SystemExit(main())
