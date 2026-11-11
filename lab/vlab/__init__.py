"""Helpers for the laptop fault lab (docs/05). Lab code only: engines never import this package."""

from pathlib import Path

#: lab/ (this package's parent folder).
LAB_DIR = Path(__file__).resolve().parents[1]
#: Raw captures, answer keys and the attempt log (git-ignored; 05 §9).
CAPTURES_DIR = LAB_DIR / "captures"
