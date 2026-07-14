from __future__ import annotations

from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup


APP_DIR = Path(__file__).resolve().parent / "app"

EXCLUDED_FILES = {
    "__init__.py",
    "main.py",
    "schemas.py",
    "version.py",
}

EXCLUDED_DIRS = {
    "admin",
    "__pycache__",
}


def build_extensions() -> list[Extension]:
    extensions: list[Extension] = []
    for py_file in APP_DIR.rglob("*.py"):
        rel = py_file.relative_to(APP_DIR)
        if py_file.name in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        module_parts = ("app", *rel.with_suffix("").parts)
        extensions.append(Extension(".".join(module_parts), [str(py_file)]))
    return extensions


setup(
    name="xcn-similarity",
    ext_modules=cythonize(
        build_extensions(),
        compiler_directives={"language_level": "3"},
        annotate=False,
    ),
    zip_safe=False,
)
