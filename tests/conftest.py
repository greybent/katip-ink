# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""conftest.py — pytest configuration for gnome-overlay tests."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so imports like
# `from core.state_machine import ...` work without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))
