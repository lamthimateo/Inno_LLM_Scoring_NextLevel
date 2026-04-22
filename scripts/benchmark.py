#!/usr/bin/env python3
"""
Backward-compatible wrapper.

The implementation moved to `src/benchmark/cli.py` to keep the project cleaner
and more testable. This file remains so existing README commands keep working.
"""

import os
import sys


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.benchmark.cli import main


if __name__ == "__main__":
    main()
