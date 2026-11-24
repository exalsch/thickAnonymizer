"""GLiNER inference on onnxruntime, without torch, transformers or the gliner package.

The gliner package needs PyTorch, which takes the exe from about 0,5 GB to
about 3 GB. The same model exported to ONNX runs on onnxruntime and the
tokenizers library alone, and gives the same entities (checked on the
23.11.2026 benchmark, docs/reviews/2026-11-23-model-research.md).

This reproduces the gliner 0.2.x pipeline for uni-encoder span models
(span_mode "markerV0", for example urchade/gliner_multi_pii-v1):

1. Split the text into words with GLiNER's whitespace splitter.
2. Prefix the prompt  <<ENT>> label  <<ENT>> label ... <<SEP>>  and tokenize
   the whole sequence as pre-split words.
3. Mark the first subtoken of each text word in words_mask (1-based word
   number, 0 for prompt and special tokens and for later subtokens).
4. Score every span of up to max_width words, apply a sigmoid, keep the spans
   above the threshold and resolve overlaps greedily by score (flat NER).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from thickanon.detectors.gliner import _WORD, iter_word_windows

_WINDOW_OVERLAP_WORDS = 32


class OnnxGliner:
    """A GLiNER model with the predict_entities() interface of gliner.GLiNER."""

    def __init__(self, config: dict, tokenizer, session):
        self.config = SimpleNamespace(
            max_len=int(config.get("max_len", 384)),
            max_width=int(config.get("max_width", 12)),
            ent_token=config.get("ent_token", "<<ENT>>"),
            sep_token=config.get("sep_token", "<<SEP>>"),
        )
        self.tokenizer = tokenizer
        self.session = session
        self._input_names = {i.name for i in session.get_inputs()}

    @classmethod
    def from_dir(cls, model_dir, onnx_file="onnx/model.onnx", providers=None, threads=None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        config = json.loads((model_dir / "gliner_config.json").read_text(encoding="utf-8"))
        tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            options.intra_op_num_threads = threads
        session = ort.InferenceSession(str(model_dir / onnx_file), options,
                                       providers=providers or ["CPUExecutionProvider"])
        return cls(config, tokenizer, session)

    def predict_entities(self, text, labels, threshold=0.5):
        """Entities as dicts with start, end, text, label and score.

        Text longer than the model's word limit is windowed here too, so no
        caller can lose the end of a text to silent truncation.
        """
        words = [(m.group(), m.start(), m.end()) for m in _WORD.finditer(text)]
        if not words or not labels:
            return []
        if len(words) <= self.config.max_len:
            found = self._predict_words(words, labels, threshold)
        else:
            found = []
            for base, own_start, own_end, window in iter_word_windows(
                    text, self.config.max_len, _WINDOW_OVERLAP_WORDS):
                window_words = [(m.group(), base + m.start(), base + m.end())
                                for m in _WORD.finditer(window)]
                found += [e for e in self._predict_words(window_words, labels, threshold)
                          if own_start <= e["start"] < own_end]
        for entity in found:
            entity["text"] = text[entity["start"]:entity["end"]]
        return found

    def _predict_words(self, words, labels, threshold):
        cfg = self.config
        prompt = []
        for label in labels:
            prompt += [cfg.ent_token, label]
        prompt.append(cfg.sep_token)

        encoding = self.tokenizer.encode(prompt + [w for w, _, _ in words], is_pretokenized=True)
        words_mask, previous, word_number = [], None, 0
        for word_id in encoding.word_ids:
            if word_id is None or word_id == previous:
                words_mask.append(0)
            else:
                word_number = word_id - len(prompt) + 1
                words_mask.append(word_number if word_id >= len(prompt) else 0)
            previous = word_id

        n, width = len(words), cfg.max_width
        starts = np.repeat(np.arange(n), width)
        ends = starts + np.tile(np.arange(width), n)
        feeds = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.ones((1, len(encoding.ids)), dtype=np.int64),
            "words_mask": np.array([words_mask], dtype=np.int64),
            "text_lengths": np.array([[n]], dtype=np.int64),
            "span_idx": np.stack([starts, ends], -1)[None].astype(np.int64),
            "span_mask": (ends < n)[None],
        }
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        logits = self.session.run(None, feeds)[0][0]            # [words, width, labels]
        with np.errstate(over="ignore"):
            probs = 1.0 / (1.0 + np.exp(-logits))

        candidates = []
        for s, k, c in zip(*np.nonzero(probs > threshold)):
            s, k, c = int(s), int(k), int(c)
            if s + k >= n:
                continue
            candidates.append((s, s + k, c, float(probs[s, k, c])))
        candidates.sort(key=lambda span: -span[3])
        kept = []
        for span in candidates:
            if any(not (span[0] > other[1] or other[0] > span[1]) for other in kept):
                continue
            kept.append(span)
        return [{"start": words[s][1], "end": words[e][2], "label": labels[c], "score": score}
                for s, e, c, score in sorted(kept)]
