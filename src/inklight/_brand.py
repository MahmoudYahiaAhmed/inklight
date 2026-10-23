"""Brand constants in one place, so the product can be renamed without a code hunt."""

from __future__ import annotations

import os

NAME = os.environ.get("INKLIGHT_BRAND_NAME", "Inklight")
CLI = "inklight"
TAGLINE = "See documents. Understand meaning. Take action."
HOME_ENV = "INKLIGHT_HOME"
CONFIG_ENV = "INKLIGHT_CONFIG"

# Palette shared by the CLI theme, web UI and docs.
GRAPHITE = "#0B0F14"
CYAN = "#22D3EE"
AMBER = "#F5B544"
