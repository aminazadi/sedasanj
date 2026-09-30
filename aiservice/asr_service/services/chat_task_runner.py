"""Isolated inference entry point for deadline-bound asynchronous chat tasks."""

import json
import os
import sys

from asr_service.domain.catalog import load_custom_models
from asr_service.services.text_processing import chat_completion


def main():
    # Linux Docker: never leave orphaned inference running when the API process dies.
    if sys.platform == "linux":
        import ctypes
        import signal

        parent = os.getppid()
        libc = ctypes.CDLL(None)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
            sys.exit(1)
    load_custom_models()
    payload = json.load(sys.stdin)
    result = chat_completion(payload["model"], payload["messages"], **payload["options"])
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
