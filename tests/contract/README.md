# ConversationEngine Contract Tests

> Implementation-agnostic tests that every `ConversationEngine` implementation
> (LocalEngine, ZchatEngine, …) must pass.

## Running

```bash
pytest tests/contract/ -v
```

Without an implementation registered, tests skip with
`contract: no engine factory registered`. This is expected during M0
(contract-freeze phase); actual implementations land M1+.

## Registering an implementation

Set the `AUTOSERVICE_CONTRACT_ENGINE_FACTORY` env var to a dotted path of
an `async () -> ConversationEngine` factory, e.g.:

```bash
export AUTOSERVICE_CONTRACT_ENGINE_FACTORY=autoservice.engines.local:make_local_engine
pytest tests/contract/ -v
```

Or register via `conftest.py` in a downstream test package:

```python
from tests.contract.conftest import register_engine_factory
register_engine_factory(make_local_engine)
```

## Test layout

| file | spec section | what it verifies |
|---|---|---|
| `test_types.py` | §2 | Dataclass frozen, enum values, timer defaults |
| `test_lifecycle.py` | §3 lifecycle | create/get/close/set_csat + idempotency |
| `test_participants.py` | §3 Participants, §7.1 #8 | join auto-switches auto→copilot; last op leave → auto |
| `test_mode.py` | §3 Mode, Q4 | switch_mode serialization, mode.noop on target==current |
| `test_messages.py` | §3 Messages, Q9 | send/edit/delete/get_messages; viewer_role filter; since/before exclusive |
| `test_gate.py` | §4, Q5, Q7 | Gate downgrade matrix; only downgrades; irreversibility (invariant #5) |
| `test_commands.py` | §6.1 | handle_command permission matrix (role × command) |
| `test_events.py` | §5, Q6 | subscribe scopes; since_sequence int vs ULID; mode.noop / hook.failed emission |
| `test_invariants.py` | §7.1 | All 8 invariants as end-to-end scenarios |

## Reviewer signoff

- DevA (author) · DevB (reviewer) · #21
