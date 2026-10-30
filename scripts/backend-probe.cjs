/** Shared, import-free interpreter preflight for development launchers. */

const PROBE_CODE = [
  'import importlib.util, sys',
  'required = ("fastapi", "uvicorn", "websockets", "asyncssh", "pydantic", "pydantic_settings", "jose", "sqlalchemy", "aiosqlite", "alembic", "cryptography", "aiofiles", "structlog", "multipart", "dotenv", "httpx", "matplotlib", "numpy", "pandas", "PIL", "pypdf", "fitz", "yaml")',
  'missing = [name for name in required if importlib.util.find_spec(name) is None]',
  'sys.stderr.write("missing dependencies: " + ", ".join(missing) if missing else "")',
  'sys.exit(0 if sys.version_info >= (3, 11) and not missing else 1)',
].join('; ')

module.exports = { PROBE_CODE }
