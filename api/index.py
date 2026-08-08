import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel needs the app to be exported as 'app' or 'handler'
# This is the WSGI entry point for Vercel
handler = app
