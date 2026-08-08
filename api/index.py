import sys
import os
import traceback

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify

# --- Fallback error app (shown if main app fails to import) ---
_error_app = Flask(__name__)
_import_error = {}


def _try_load():
    global _import_error
    try:
        from app import app as flask_app, db  # noqa: F401

        _db_done = {"done": False}

        @flask_app.before_request
        def _init_db():
            if not _db_done["done"]:
                try:
                    db.create_all()
                except Exception as exc:
                    flask_app.logger.warning("db.create_all skipped: %s", exc)
                finally:
                    _db_done["done"] = True

        return flask_app

    except Exception as exc:  # noqa: BLE001
        _import_error = {
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "python": sys.version,
            "database_url_set": bool(os.environ.get("DATABASE_URL")),
        }
        return None


_loaded = _try_load()

if _loaded is not None:
    app = _loaded
else:
    app = _error_app

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def _show_import_error(path=""):
        return jsonify(_import_error), 500


# Vercel requires a top-level 'app', 'application', or 'handler'
handler = app
