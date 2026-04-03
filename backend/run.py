#!/usr/bin/env python3
"""
Arabic Ontology Chat API - Main Entry Point

This is the main entry point for running the Arabic Ontology Chat API.
The application is organized in a modular structure for better maintainability.
"""

import sys
import os
from pathlib import Path

# Load environment variables from .env if it exists
base_dir = Path(__file__).resolve().parent
env_path = base_dir / ".env"
if env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        # dotenv is optional; fallback to environment variables
        pass

# Add the backend directory to Python path
sys.path.insert(0, str(base_dir))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        log_level="info"
    )
