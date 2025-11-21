#!/usr/bin/env python3
"""Questlog CLI - Activity logging from screenshots.

This module provides backward compatibility for the command-line interface.
For new code, use questlog.cli.app directly.
"""

# Backward compatibility: redirect to new CLI
from questlog.cli.app import app, main

__all__ = ["app", "main"]
