import os
import sys

addon_root = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(addon_root, "lib")
if lib_path in sys.path:
    sys.path.remove(lib_path)
sys.path.insert(0, lib_path)

if os.environ.get("NVDA_AI_ASSISTANT_DEBUG"):
    try:
        import markdown as _debug_markdown
        import pygments as _debug_pygments
        print("markdown:", getattr(_debug_markdown, "__file__", repr(_debug_markdown)))
        print("pygments:", getattr(_debug_pygments, "__file__", repr(_debug_pygments)))
    except Exception:
        import traceback
        traceback.print_exc()

from .plugin.controller import GlobalPlugin

__all__ = ["GlobalPlugin"]
