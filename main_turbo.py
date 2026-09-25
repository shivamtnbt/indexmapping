"""
Main entry point for PBI Indexing Tool - TURBO / BLAZING FAST EDITION
Powered by DuckDB Vectorized Multi-Threaded C++ Engine.
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from turbo.ui import launch

if __name__ == "__main__":
    launch()
