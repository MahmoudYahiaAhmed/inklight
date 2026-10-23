"""Structured extraction: typed values, field specs and document classification."""

from .classify import DOC_TYPES, SINGULAR, classify
from .fields import CATALOG, FieldSpec, extract_record, load_schema, resolve_field, schema_from_dict
from .values import parse_date, parse_dates, parse_money, parse_number

__all__ = [
    "CATALOG",
    "DOC_TYPES",
    "SINGULAR",
    "FieldSpec",
    "classify",
    "extract_record",
    "load_schema",
    "parse_date",
    "parse_dates",
    "parse_money",
    "parse_number",
    "resolve_field",
    "schema_from_dict",
]
