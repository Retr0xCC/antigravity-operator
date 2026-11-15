"""Entry point when executed as python3 -m muxpress."""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
