"""
PBI Indexer - Entry Point
Consolidation, Month-wise Matching & Index Generator Tool
"""

import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from ui.app import run_app

if __name__ == "__main__":
    run_app()
