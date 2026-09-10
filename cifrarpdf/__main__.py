"""Permite «python -m cifrarpdf …» durante el desarrollo."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
