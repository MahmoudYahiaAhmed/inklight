# SPDX-FileCopyrightText: The Docling Contributors
# SPDX-License-Identifier: MIT
"""Table structure: TableFormer on each table region, its cells matched to the page's text cells."""

import copy
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy
from docling_core.types.doc import BoundingBox, DocItemLabel, TableCell
from docling_core.types.doc.page import (
    BoundingRectangle,
    TextCellUnit,
)

from .common import TimeRecorder
from .datamodel import Page, Table, TableStructurePrediction
from .options import TABLE_IMAGE_SCALE

_log = logging.getLogger(__name__)


class TableStructureModel:
    def __init__(self, artifacts_path: Path, num_threads: int, do_cell_matching: bool = True) -> None:
        """``artifacts_path``: the folder with tm_config.json and the TableFormer weights (accurate or fast)."""
        import inklight.backends.structure.tableformer.common as c
        from inklight.backends.structure.tableformer.data_management.tf_predictor import TFPredictor

        self.do_cell_matching = do_cell_matching
        self.tm_config = c.read_config(f"{artifacts_path}/tm_config.json")
        self.tm_config["model"]["save_dir"] = artifacts_path
        self.tm_model_type = self.tm_config["model"]["type"]
        self.tf_predictor = TFPredictor(self.tm_config, "cpu", num_threads)
        self.scale = TABLE_IMAGE_SCALE  # Scale up table input images to 144 dpi


    def predict_tables(
        self,
        conv_res: Any,
        pages: Sequence[Page],
    ) -> Sequence[TableStructurePrediction]:
        pages = list(pages)
        predictions: list[TableStructurePrediction] = []

        for page in pages:
            assert page._backend is not None
            if not page._backend.is_valid():
                existing_prediction = (
                    page.predictions.tablestructure or TableStructurePrediction()
                )
                page.predictions.tablestructure = existing_prediction
                predictions.append(existing_prediction)
                continue

            with TimeRecorder(conv_res, "table_structure"):
                assert page.predictions.layout is not None
                assert page.size is not None

                table_prediction = TableStructurePrediction()
                page.predictions.tablestructure = table_prediction

                in_tables = [
                    (
                        cluster,
                        [
                            round(cluster.bbox.l) * self.scale,
                            round(cluster.bbox.t) * self.scale,
                            round(cluster.bbox.r) * self.scale,
                            round(cluster.bbox.b) * self.scale,
                        ],
                    )
                    for cluster in page.predictions.layout.clusters
                    if cluster.label
                    in [DocItemLabel.TABLE, DocItemLabel.DOCUMENT_INDEX]
                ]
                if not in_tables:
                    predictions.append(table_prediction)
                    continue

                page_input = {
                    "width": page.size.width * self.scale,
                    "height": page.size.height * self.scale,
                    "image": numpy.asarray(page.get_image(scale=self.scale)),
                }

                # Resolved once per page: the segmented page is the same for
                # every table on it, and get_cells_in_bbox already walks all of
                # its cells per call.
                sp = page._backend.get_segmented_page()

                for table_cluster, tbl_box in in_tables:
                    # Check if word-level cells are available from backend:
                    if sp is not None:
                        tcells = sp.get_cells_in_bbox(
                            cell_unit=TextCellUnit.WORD,
                            bbox=table_cluster.bbox,
                        )
                        if len(tcells) == 0:
                            # In case word-level cells yield empty
                            tcells = table_cluster.cells
                    else:
                        # Otherwise - we use normal (line/phrase) cells
                        tcells = table_cluster.cells
                    tokens = []
                    for c in tcells:
                        # Only allow non empty strings (spaces) into the cells of a table
                        if len(c.text.strip()) > 0:
                            new_cell = copy.deepcopy(c)
                            new_cell.rect = BoundingRectangle.from_bounding_box(
                                new_cell.rect.to_bounding_box().scaled(scale=self.scale)
                            )
                            tokens.append(
                                {
                                    "id": new_cell.index,
                                    "text": new_cell.text,
                                    "bbox": new_cell.rect.to_bounding_box().model_dump(),
                                }
                            )
                    page_input["tokens"] = tokens

                    tf_output = self.tf_predictor.multi_table_predict(
                        page_input, [tbl_box], do_matching=self.do_cell_matching
                    )
                    table_out = tf_output[0]
                    table_cells = []
                    for element in table_out["tf_responses"]:
                        if not self.do_cell_matching:
                            the_bbox = BoundingBox.model_validate(
                                element["bbox"]
                            ).scaled(1 / self.scale)
                            text_piece = page._backend.get_text_in_rect(the_bbox)
                            element["bbox"]["token"] = text_piece

                        tc = TableCell.model_validate(element)
                        if tc.bbox is not None:
                            tc.bbox = tc.bbox.scaled(1 / self.scale)
                        table_cells.append(tc)

                    assert "predict_details" in table_out

                    # Retrieving cols/rows, after post processing:
                    num_rows = table_out["predict_details"].get("num_rows", 0)
                    num_cols = table_out["predict_details"].get("num_cols", 0)
                    otsl_seq = (
                        table_out["predict_details"]
                        .get("prediction", {})
                        .get("rs_seq", [])
                    )

                    tbl = Table(
                        otsl_seq=otsl_seq,
                        table_cells=table_cells,
                        num_rows=num_rows,
                        num_cols=num_cols,
                        id=table_cluster.id,
                        page_no=page.page_no,
                        cluster=table_cluster,
                        label=table_cluster.label,
                    )

                    table_prediction.table_map[table_cluster.id] = tbl

                predictions.append(table_prediction)

        return predictions

    # FIXME: this method is here to test the quality and performance of the
    # bare TableFormer model on crops of tables in the ground-truth. In the near
    # future, we expect this method to be used in `predict_tables`!
