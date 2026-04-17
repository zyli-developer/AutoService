"""Root-level conftest: registers LocalEngine as the contract test factory.

Uses environment variable to avoid import-order issues between conftest files.
"""

import os

os.environ.setdefault(
    "AUTOSERVICE_CONTRACT_ENGINE_FACTORY",
    "tests.conftest:create_local_engine",
)


async def create_local_engine():
    from autoservice.conversation_engine import LocalEngine
    return LocalEngine()
