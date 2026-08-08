import sys
import os
import traceback

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_import_error = None
_flask_app = None

try:
    from app import app as flask_app, db
    _flask_app = flask_app

    _db_initialized = False

    @flask_app.before_request
    def _init_db_lazy():
        global _db_initialized
        if not _db_initialized:
            try:
                db.create_all()
            except Exception as e:
                flask_app.logger.warning(f"db.create_all skipped: {e}")
            finally:
                _db_initialized = True

    handler = flask_app

except Exception as e:
    _import_error = {
        "error": str(e),
        "type": type(e).__name__,
        "traceback": traceback.format_exc(),
        "python_version": sys.version,
        "env_keys": [k for k in os.environ if "DATABASE" in k or "SECRET" in k or "MAIL" in k],
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
    }

    from flask import Flask, jsonify

    _err_app = Flask(__name__)

    @_err_app.route("/", defaults={"path": ""})
    @_err_app.route("/<path:path>")
    def _show_error(path=""):
        return jsonify(_import_error), 500

    handler = _err_app
