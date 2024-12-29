import sys
import os

# Add your project directory to the sys.path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_dir)

# Import your Flask app
from app import app as application