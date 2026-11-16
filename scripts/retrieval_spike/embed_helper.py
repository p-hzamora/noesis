"""Embedding helper for the spike: run with Vectra's interpreter, `python -I embed_helper.py`.

It keeps `sentence-transformers` and `torch` out of Noesis's environment (user decision
2026-11-15). Protocol: one JSON object per line on stdin, one per line on stdout. After start-up
the helper prints `{"ready": true, "import_ms": .., "load_ms": .., ...}`; then:

    {"op": "encode", "texts": [...]}  ->  {"vectors": [[...]], "ms": ..}   (L2-normalised)
    {"op": "tokens", "texts": [...]}  ->  {"counts": [...], "max_seq_length": ..}
    {"op": "quit"}

Usage: python -I embed_helper.py MODEL_ID. The model must already be in the Hugging Face cache
(`HF_HOME`); the helper runs offline and never downloads.
"""

import json
import os
import sys
import time
from typing import Any


def main() -> None:
    """Load the model once, then answer requests until `quit` or end of input."""
    out = sys.stdout
    sys.stdout = sys.stderr  # library noise must never reach the protocol stream
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    model_id = sys.argv[1]
    started = time.perf_counter()
    from sentence_transformers import SentenceTransformer  # heavy import (torch)

    imported = time.perf_counter()
    model: Any = SentenceTransformer(model_id)
    loaded = time.perf_counter()
    out.write(
        json.dumps(
            {
                "ready": True,
                "model": model_id,
                "import_ms": round((imported - started) * 1000, 1),
                "load_ms": round((loaded - imported) * 1000, 1),
                "dimension": model.get_embedding_dimension(),
                "max_seq_length": model.max_seq_length,
            }
        )
        + "\n"
    )
    out.flush()
    for line in sys.stdin:
        request = json.loads(line)
        if request["op"] == "quit":
            break
        began = time.perf_counter()
        if request["op"] == "encode":
            vectors = model.encode(
                request["texts"],
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            reply: dict[str, Any] = {
                "vectors": [[float(v) for v in vector] for vector in vectors],
                "ms": round((time.perf_counter() - began) * 1000, 2),
            }
        elif request["op"] == "tokens":
            tokenizer = model.tokenizer
            counts = [len(tokenizer(text)["input_ids"]) for text in request["texts"]]
            reply = {"counts": counts, "max_seq_length": model.max_seq_length}
        else:
            reply = {"error": f"unknown op {request['op']}"}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
