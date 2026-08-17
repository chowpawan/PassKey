"""Test environment setup.

This runs before pytest imports any test module, which matters: app.db builds its
engine at import time from a cached Settings, so anything we want to override has
to be in os.environ before the first `import app.*` anywhere.

The important override is DB_URL. The test fixtures truncate every table between
tests, so pointing them at the dev database (the .env default) means running the
suite deletes whatever you registered in the browser — passkey credentials included,
which can't be recovered. Tests get their own throwaway file instead.
"""

import base64
import os

# Set, don't setdefault: a DB_URL inherited from the shell or .env must not win here.
os.environ["DB_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ.setdefault("VAULT_KEY", base64.b64encode(b"\x00" * 32).decode())
os.environ.setdefault("SESSION_SECRET", "test-secret-test-secret-test-secret-test")
