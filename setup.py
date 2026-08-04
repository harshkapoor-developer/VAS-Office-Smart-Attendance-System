"""
setup.py
----------
Standard packaging metadata. This project is primarily run as a
standalone desktop app (`python main.py`), not installed as a pip
library - this file exists mainly so `pip install -e .` works for
development, and so the project has proper metadata if it's ever
packaged for distribution.
"""

from __future__ import annotations

from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent


def _read_requirements() -> list[str]:
    req_file = ROOT / "requirements.txt"
    lines = req_file.read_text().splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def _read_long_description() -> str:
    readme = ROOT / "README.md"
    return readme.read_text() if readme.exists() else ""


setup(
    name="smart-attendance-system",
    version="1.0.0",
    description="Offline, AI-powered face recognition attendance system for Windows and Raspberry Pi 5",
    long_description=_read_long_description(),
    long_description_content_type="text/markdown",
    author="Harsh Kapoor",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests", "tests.*"]),
    py_modules=["config", "main", "take_photos", "preview_recognition", "validate_environment"],
    install_requires=_read_requirements(),
    entry_points={
        "console_scripts": [
            "smart-attendance=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Office/Business",
    ],
)
