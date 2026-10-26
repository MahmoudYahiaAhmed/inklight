"""Shared pieces of the structure stages: the layout label groups, the page-model base and a timing hook."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any

from docling_core.types.doc import DocItemLabel

if TYPE_CHECKING:
    from .datamodel import Page

TEXT_ELEM_LABELS = [
    DocItemLabel.TEXT,
    DocItemLabel.FOOTNOTE,
    DocItemLabel.CAPTION,
    DocItemLabel.CHECKBOX_UNSELECTED,
    DocItemLabel.CHECKBOX_SELECTED,
    DocItemLabel.SECTION_HEADER,
    DocItemLabel.PAGE_HEADER,
    DocItemLabel.PAGE_FOOTER,
    DocItemLabel.CODE,
    DocItemLabel.LIST_ITEM,
    DocItemLabel.FORMULA,
]
PAGE_HEADER_LABELS = [DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER]
TABLE_LABELS = [DocItemLabel.TABLE, DocItemLabel.DOCUMENT_INDEX]
FIGURE_LABEL = DocItemLabel.PICTURE
FORMULA_LABEL = DocItemLabel.FORMULA
CONTAINER_LABELS = [DocItemLabel.FORM, DocItemLabel.KEY_VALUE_REGION]


class BasePageModel(ABC):
    @abstractmethod
    def __call__(self, conv_res: Any, page_batch: Iterable[Page]) -> Iterable[Page]:
        pass


class ProfilingScope(str, Enum):  # noqa: UP042 - upstream definition
    PAGE = "page"
    DOCUMENT = "document"


@contextmanager
def TimeRecorder(conv_res: Any, key: str, scope: ProfilingScope = ProfilingScope.PAGE):  # noqa: N802 - upstream name
    """Upstream records stage timings here; Inklight times the whole run instead."""
    yield
