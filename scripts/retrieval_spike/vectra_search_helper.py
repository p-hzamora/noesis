"""Resident Vectra search helper, run with Vectra's interpreter: `python -I vectra_search_helper.py ENV_FILE`.

It wires Vectra's own handlers (`build_retrieval`, so Vectra's embedder adapter, query prefix rule,
LanceDB store and document grouper) and keeps the model loaded between queries. Protocol: one JSON
object per line on stdin and stdout. After start-up: `{"ready": true, "import_ms", "load_ms"}`;
then `{"op": "search", "collection", "text", "top_k"}` -> `{"paths": [...], "scores": [...], "ms"}`
(or `{"error": ...}`), and `{"op": "quit"}`. Tables are reopened per call, so a `vectra sync` run
by another process is visible. Offline: the model must be in the Hugging Face cache.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


async def serve(env_file: str, out: Any) -> None:
    """Load once, then answer requests until `quit` or end of input."""
    started = time.perf_counter()
    from vectra.bounded_context.retrieval.application.handlers.queries import (
        SearchCollectionQuery,
    )
    from vectra.core import load_environment
    from vectra.interfaces.cli import bootstrap

    imported = time.perf_counter()
    environment = load_environment(Path(env_file))
    embedder = bootstrap.build_embedder(environment)
    handlers = bootstrap.build_retrieval(environment, embedder=embedder)
    await embedder.embed_query("warm up")  # loads the model
    loaded = time.perf_counter()
    out.write(
        json.dumps(
            {
                "ready": True,
                "import_ms": round((imported - started) * 1000, 1),
                "load_ms": round((loaded - imported) * 1000, 1),
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
        try:
            result = await handlers.search.handle(
                SearchCollectionQuery(
                    collection=request["collection"],
                    text=request["text"],
                    top_k=request["top_k"],
                )
            )
            reply: dict[str, Any] = {
                "paths": [hit.path for hit in result.hits],
                "scores": [hit.score for hit in result.hits],
                "ms": round((time.perf_counter() - began) * 1000, 2),
            }
        except Exception as error:
            reply = {"error": f"{type(error).__name__}: {error}"}
        out.write(json.dumps(reply) + "\n")
        out.flush()


def main() -> None:
    """Entry point; library noise goes to stderr, never to the protocol stream."""
    out = sys.stdout
    sys.stdout = sys.stderr
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    asyncio.run(serve(sys.argv[1], out))


if __name__ == "__main__":
    main()
