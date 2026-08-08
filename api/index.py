import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db

# Auto-create all database tables on first deploy (Supabase PostgreSQL)
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Warning: db.create_all() failed: {e}")

# Vercel WSGI entry point
handler = app
