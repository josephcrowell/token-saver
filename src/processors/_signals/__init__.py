"""Shared signal detection utilities for processors.

This package contains helper functions and classes for detecting various
signals in command output (errors, entropy, adaptive sizing, etc.).

These utilities are NOT processors themselves and will not be auto-discovered
by the processor registry. They are imported explicitly by processors that need them.
"""