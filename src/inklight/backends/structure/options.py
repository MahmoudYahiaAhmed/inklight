"""The settings the structure stages run with: the values Inklight has always used, fixed here."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutPostprocessorOptions:
    keep_empty_clusters: bool = False
    skip_cell_assignment: bool = False
    create_orphan_clusters: bool = True


LAYOUT_SCORE_THRESHOLD = 0.3  # detections below this score are dropped
LAYOUT_IMAGE_SCALE = 1.0  # the layout model sees the page at 72 dpi
TABLE_IMAGE_SCALE = 2.0  # table images go to TableFormer at 144 dpi
