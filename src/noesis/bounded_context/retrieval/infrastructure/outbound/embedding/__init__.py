"""Embedding runtime adapters: pinned model cache, ONNX engine, resident client and probe.

Modules that need the optional `semantic` extra (numpy, onnxruntime, tokenizers) are imported
by the composition root only once that extra is known to be installed.
"""
