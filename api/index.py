import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db

# Lazy DB init — runs once per cold start, inside app context
_db_initialized = False

@app.before_request
def init_db():
    global _db_initialized
    if not _db_initialized:
        try:
            with app.app_context():
                db.create_all()
            _db_initialized = True
        except Exception as e:
            app.logger.warning(f"db.create_all() skipped: {e}")
            _db_initialized = True  # Don't retry on every request

# Vercel WSGI entry point
handler = app
