"""Storage adapters."""

from .oracle_sql import OracleSqlStorage, OracleSqlStorageError

__all__ = ["OracleSqlStorage", "OracleSqlStorageError"]
