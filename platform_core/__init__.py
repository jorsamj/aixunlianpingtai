"""Testable core services for the training platform."""

# Install bounded SQLite ID operations as soon as the package is imported. This keeps legacy
# callers safe from SQLite variable limits while larger app.py flows are migrated incrementally.
from . import material_repository_batch as _material_repository_batch  # noqa: F401,E402
