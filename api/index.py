import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db  # noqa: E402

# Lazy one-time DB table creation
_db_ready = [False]


@app.before_request
def _init_db_once():
    if not _db_ready[0]:
        try:
            db.create_all()
        except Exception as exc:  # noqa: BLE001
            app.logger.warning("db.create_all skipped: %s", exc)
        finally:
            _db_ready[0] = True


# Vercel needs a top-level name: 'app', 'application', or 'handler'
handler = app
