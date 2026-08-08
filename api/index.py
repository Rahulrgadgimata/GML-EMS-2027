"""Vercel serverless entry point.

Schema setup lives in ``app.init_database`` and runs on the first request, so
nothing here can fail while the module is being imported — an exception at
import time gives FUNCTION_INVOCATION_FAILED with no usable traceback.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402

# Vercel needs a top-level name: 'app', 'application', or 'handler'.
handler = app
