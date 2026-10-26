"""Model execution inside Inklight: OCR (``backends.ocr``) and document structure (``backends.structure``).

The code here loads the pinned model files (``inklight.modelstore``) and runs them with ONNX Runtime (OCR, layout)
and PyTorch (table structure). It is kept close to the implementations it was taken from, so that it can be compared
line by line; each folder's LICENSE file covers its code.
"""
