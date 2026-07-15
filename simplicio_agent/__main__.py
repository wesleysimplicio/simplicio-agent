"""Enable ``python -m simplicio_agent`` as a canonical console entry.

Forwards to :func:`simplicio_agent.entry.main` so the public package is a
runnable entry point alongside the installed ``simplicio-agent`` command.
"""

from __future__ import annotations

from .entry import main

if __name__ == "__main__":
    main()
