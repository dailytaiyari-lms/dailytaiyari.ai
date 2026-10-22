"""Editable tagging config (decision D4): tags.yaml + exams/<exam>.yaml.

Edit the YAML, then run ``manage.py sync_taxonomy``. The tagger reads only
from the database, never from these files directly.
"""
from pathlib import Path

TAXONOMY_DIR = Path(__file__).resolve().parent
TAGS_FILE = TAXONOMY_DIR / 'tags.yaml'
EXAMS_DIR = TAXONOMY_DIR / 'exams'
