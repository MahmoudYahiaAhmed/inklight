# SPDX-FileCopyrightText: The Docling Contributors
# SPDX-License-Identifier: MIT
"""Layout detection: the Heron RT-DETR v2 layout model (its ONNX export) on each page image at 72 dpi.

Preprocessing is the model's own (preprocessor_config.json): a bilinear, antialiased resize to 640 x 640 of the
uint8 RGB image, with no rescaling or normalisation (the exported graph does both). The model returns labels, boxes
in the page image's pixels and scores; detections under the score threshold are dropped and the boxes are clamped to
the page and expressed in points.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from docling_core.types.doc import BoundingBox, CoordOrigin, DocItemLabel
from PIL import Image

from .datamodel import Cluster, LayoutPrediction, Page
from .options import LAYOUT_IMAGE_SCALE, LAYOUT_SCORE_THRESHOLD

_log = logging.getLogger(__name__)


class LayoutModel:
    def __init__(self, model_dir: Path, num_threads: int) -> None:
        import onnxruntime as ort

        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        preprocess = json.loads((model_dir / "preprocessor_config.json").read_text(encoding="utf-8"))
        size = preprocess["size"]
        self._size = [int(size["height"]), int(size["width"])]
        self._label_map = _label_map(config["id2label"])
        options = ort.SessionOptions()
        options.intra_op_num_threads = num_threads
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(model_dir / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._unmapped: set[int] = set()

    def _pixels(self, images: list[Image.Image]) -> np.ndarray:
        import torch
        from torchvision.transforms.v2 import functional as tvf

        resized = [
            tvf.resize(
                tvf.pil_to_tensor(image),
                self._size,
                interpolation=tvf.InterpolationMode.BILINEAR,
                antialias=True,
            )
            for image in images
        ]
        return torch.stack(resized).numpy()

    def predict_layout(self, conv_res: Any, pages: Sequence[Page]) -> Sequence[LayoutPrediction]:
        pages = list(pages)
        batch: list[Image.Image] = []
        indices: list[int] = []
        for idx, page in enumerate(pages):
            assert page._backend is not None
            if not page._backend.is_valid():
                continue
            image = page.get_image(scale=LAYOUT_IMAGE_SCALE)
            if image is None:
                continue
            batch.append(image.convert("RGB"))
            indices.append(idx)
        predictions = [page.predictions.layout or LayoutPrediction() for page in pages]
        if batch:
            sizes = np.array([[im.width, im.height] for im in batch], dtype=np.int64)
            labels, boxes, scores = self._session.run(
                None, {"images": self._pixels(batch), "orig_target_sizes": sizes}
            )[:3]
            for i, (idx, image) in enumerate(zip(indices, batch, strict=True)):
                clusters = self._clusters(pages[idx], image, labels[i], scores[i], boxes[i])
                predictions[idx] = LayoutPrediction(clusters=clusters)  # post-processing runs next
        for page, prediction in zip(pages, predictions, strict=True):
            page.predictions.layout = prediction
        return predictions

    def _clusters(self, page: Page, image: Image.Image, labels: Any, scores: Any, boxes: Any) -> list[Cluster]:
        assert page.size is not None
        width, height = page.size.width, page.size.height
        sx, sy = width / image.width, height / image.height
        clusters: list[Cluster] = []
        idx = -1
        for label_id, score, box in zip(labels, scores, boxes, strict=True):
            score = float(score)
            if score < LAYOUT_SCORE_THRESHOLD:
                continue
            idx += 1  # numbered over the detections kept, as upstream
            label = self._label_map.get(int(label_id))
            if label is None:
                if int(label_id) not in self._unmapped:
                    self._unmapped.add(int(label_id))
                    _log.warning("Dropping detections with label id %s, absent from the model's id2label", label_id)
                continue
            x0, y0, x1, y1 = (float(v) for v in box)
            bbox = BoundingBox(  # detections can overshoot the page
                l=min(max(x0 * sx, 0.0), width),
                t=min(max(y0 * sy, 0.0), height),
                r=min(max(x1 * sx, 0.0), width),
                b=min(max(y1 * sy, 0.0), height),
                coord_origin=CoordOrigin.TOPLEFT,
            )
            clusters.append(Cluster(id=idx, label=label, confidence=score, bbox=bbox, cells=[]))
        return clusters


def _label_map(id2label: dict[str, str]) -> dict[int, DocItemLabel]:
    out = {}
    for key, name in id2label.items():
        try:
            out[int(key)] = DocItemLabel[name.upper()]
        except KeyError as exc:
            raise RuntimeError(f"Layout label {name!r} (id {key}) is not a known document item label") from exc
    return out
