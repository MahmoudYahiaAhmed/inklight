"""Three small ONNX models, each under 200M parameters, run on ONNX Runtime CPU.

* ``Embedder`` — bge-small-en-v1.5 (33M): semantic retrieval.
* ``Reader``   — DistilBERT SQuAD (66M): extractive QA. It can only answer with
  a span copied from the evidence, so it cannot invent facts.
* ``Writer``   — SmolLM2-135M-Instruct: intent scoring and optional phrasing.
  Its output is always verified against the evidence before use.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import ModelUnavailable


def _session(path: Path, threads: int) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - indra-ocr depends on it
        raise ModelUnavailable("onnxruntime is not installed") from exc
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.log_severity_level = 3
    try:
        return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise ModelUnavailable(f"Cannot load {path.name}: {exc}") from exc


def _tokenizer(path: Path) -> Any:
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(path))


def _feed(session: Any, ids: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
    names = {i.name for i in session.get_inputs()}
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in names:
        feed["token_type_ids"] = np.zeros_like(ids)
    return {k: v for k, v in feed.items() if k in names}


# ---------------------------------------------------------------- embedder


class Embedder:
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, files: dict[str, Path], name: str, threads: int = 4) -> None:
        self.name = name
        self.session = _session(files["onnx/model_int8.onnx"], threads)
        self.tok = _tokenizer(files["tokenizer.json"])
        self.tok.enable_truncation(max_length=512)
        self.tok.enable_padding()
        self._lock = threading.Lock()
        self.calls = 0  # ONNX Runtime inference calls, for evaluation reports

    def embed(self, texts: list[str], query: bool = False, batch: int = 16) -> np.ndarray:
        if query:
            texts = [self.QUERY_PREFIX + t for t in texts]
        out = []
        for start in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[start : start + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            with self._lock:
                self.calls += 1
                hidden = self.session.run(None, _feed(self.session, ids, mask))[0]
            cls = hidden[:, 0, :]  # bge uses the CLS vector
            out.append(cls / np.maximum(np.linalg.norm(cls, axis=1, keepdims=True), 1e-9))
        return np.concatenate(out).astype(np.float32) if out else np.zeros((0, 384), np.float32)


# ---------------------------------------------------------------- reader


@dataclass(frozen=True)
class Span:
    text: str
    score: float
    passage: int
    start: int
    end: int


class Reader:
    MAX_ANSWER_TOKENS = 40

    def __init__(self, files: dict[str, Path], name: str, threads: int = 4) -> None:
        self.name = name
        self.session = _session(files["onnx/model_int8.onnx"], threads)
        self.tok = _tokenizer(files["tokenizer.json"])
        self.tok.enable_truncation(max_length=384)
        self._lock = threading.Lock()
        self.calls = 0  # ONNX Runtime inference calls, for evaluation reports

    def answer(
        self, question: str, passages: list[str], top: int = 3, check: Callable[[], None] | None = None
    ) -> list[Span]:
        """Best answer spans across passages, scored as P(start)·P(end)."""
        spans: list[Span] = []
        for p_index, passage in enumerate(passages):
            for w_start, window in _windows(passage):
                if check:
                    check()  # cooperative cancellation between windows
                spans.extend(self._spans(question, window, p_index, w_start))
        spans.sort(key=lambda s: s.score, reverse=True)
        seen: set[str] = set()
        out = []
        for span in spans:
            key = span.text.lower()
            if key not in seen:
                seen.add(key)
                out.append(span)
            if len(out) == top:
                break
        return out

    def _spans(self, question: str, context: str, p_index: int, offset: int) -> list[Span]:
        enc = self.tok.encode(question, context)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.ones_like(ids)
        with self._lock:
            self.calls += 1
            start_logits, end_logits = self.session.run(None, _feed(self.session, ids, mask))[:2]
        seq = enc.sequence_ids
        ctx = np.array([s == 1 for s in seq])
        if not ctx.any():
            return []
        s_prob = _softmax(np.where(ctx, start_logits[0], -1e9))
        e_prob = _softmax(np.where(ctx, end_logits[0], -1e9))
        starts = np.argsort(s_prob)[::-1][:20]
        ends = np.argsort(e_prob)[::-1][:20]
        found = []
        for s in starts:
            for e in ends:
                if e < s or e - s >= self.MAX_ANSWER_TOKENS or not (ctx[s] and ctx[e]):
                    continue
                c0, c1 = enc.offsets[s][0], enc.offsets[e][1]
                text = context[c0:c1].strip()
                if text:
                    found.append(Span(text, float(s_prob[s] * e_prob[e]), p_index, offset + c0, offset + c1))
        return found


def _softmax(x: np.ndarray) -> np.ndarray:
    z = np.exp(x - x.max())
    return z / z.sum()


def _windows(text: str, size: int = 1200, stride: int = 900) -> list[tuple[int, str]]:
    if len(text) <= size:
        return [(0, text)]
    return [(i, text[i : i + size]) for i in range(0, max(len(text) - size, 0) + stride, stride)]


# ---------------------------------------------------------------- writer


class Writer:
    """SmolLM2-135M-Instruct with a KV-cache greedy decoder in NumPy."""

    MAX_PROMPT_TOKENS = 1536  # keeps latency and memory bounded on CPU

    def __init__(self, files: dict[str, Path], name: str, threads: int = 4) -> None:
        import json

        self.name = name
        self.session = _session(files["onnx/model_int8.onnx"], threads)
        self.tok = _tokenizer(files["tokenizer.json"])
        cfg = json.loads(files["config.json"].read_text(encoding="utf-8"))
        self.layers = int(cfg["num_hidden_layers"])
        self.kv_heads = int(cfg.get("num_key_value_heads", cfg["num_attention_heads"]))
        self.head_dim = int(cfg["hidden_size"]) // int(cfg["num_attention_heads"])
        self.eos = {self.tok.token_to_id("<|im_end|>"), self.tok.token_to_id("<|endoftext|>")} - {None}
        self.inputs = {i.name for i in self.session.get_inputs()}
        self._lock = threading.Lock()
        self.calls = 0  # ONNX Runtime inference calls, for evaluation reports

    @staticmethod
    def chat(system: str, user: str) -> str:
        return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"

    def _empty_cache(self) -> dict[str, np.ndarray]:
        shape = (1, self.kv_heads, 0, self.head_dim)
        return {
            f"past_key_values.{i}.{kv}": np.zeros(shape, np.float32)
            for i in range(self.layers)
            for kv in ("key", "value")
        }

    def _step(self, ids: list[int], past: dict[str, np.ndarray], pos: int) -> tuple[np.ndarray, dict]:
        n = len(ids)
        feed: dict[str, np.ndarray] = {
            "input_ids": np.array([ids], np.int64),
            "attention_mask": np.ones((1, pos + n), np.int64),
        }
        if "position_ids" in self.inputs:
            feed["position_ids"] = np.arange(pos, pos + n, dtype=np.int64)[None, :]
        feed.update(past)
        self.calls += 1
        outs = self.session.run(None, feed)
        names = [o.name for o in self.session.get_outputs()]
        present = {}
        for name, value in zip(names[1:], outs[1:], strict=True):
            present[name.replace("present.", "past_key_values.")] = value
        return outs[0], present

    def generate(self, prompt: str, max_new_tokens: int = 96, check: Callable[[], None] | None = None) -> str:
        ids = self.tok.encode(prompt).ids[-self.MAX_PROMPT_TOKENS :]
        with self._lock:
            logits, past = self._step(ids, self._empty_cache(), 0)
            pos = len(ids)
            out: list[int] = []
            for _ in range(max_new_tokens):
                if check:
                    check()  # cooperative cancellation between tokens
                nxt = int(np.argmax(logits[0, -1]))
                if nxt in self.eos:
                    break
                out.append(nxt)
                logits, past = self._step([nxt], past, pos)
                pos += 1
        return self.tok.decode(out).strip()

    def score(self, prompt: str, options: list[str]) -> list[float]:
        """Mean log-probability of each option as the continuation of ``prompt``.

        Ranking fixed choices is far more reliable for a 135M model than
        free-form generation or JSON tool calls.
        """
        base = self.tok.encode(prompt).ids
        scores = []
        with self._lock:
            for option in options:
                tail = self.tok.encode(option).ids
                logits, _ = self._step(base + tail, self._empty_cache(), 0)
                logp = logits[0] - _logsumexp(logits[0])
                total = sum(float(logp[len(base) - 1 + i, t]) for i, t in enumerate(tail))
                scores.append(total / max(len(tail), 1))
        return scores


def _logsumexp(x: np.ndarray) -> np.ndarray:
    m = x.max(axis=-1, keepdims=True)
    return m + np.log(np.exp(x - m).sum(axis=-1, keepdims=True))
