# Provider Certification Checklist

Use this checklist before a new provider is treated as a supported AgentMemory backend.

AgentMemory's provider contract requires more than method compatibility. A provider is considered certified only when it:

- returns normalized `MemoryRecord` / `DeleteResult` payloads
- enforces its declared capabilities
- throws typed provider errors instead of leaking backend exceptions
- passes the reusable provider contract harness and transport-facing checks

## 1. Interface and contract

The provider must implement the `BaseMemoryProvider` contract from `agentmemory/providers/base.py`.

Provider registration metadata should live at the provider boundary:

- provider class metadata: display name, summary, certification status, policy status, test modules
- registry descriptor: exposed through `agentmemory.providers.registry`
- provider-specific onboarding prompts: `BaseMemoryProvider.onboarding_configuration()`

Runtime lookup, certification reports, certification policy, and interactive
onboarding all consume the shared provider descriptor source.

Required behaviors:

- `add_memory` and `get_memory` return a normalized `MemoryRecord`
- `update_memory` returns a normalized `MemoryRecord` when `supports_update=True`
- `search_memory` returns a list of normalized `MemoryRecord` items, with `score` only on search results
- `list_memories` returns normalized records ordered by `updated_at desc`
- `search_memory_page` and `list_memories_page` return the canonical page shape
- `delete_memory` returns a normalized `DeleteResult` when `supports_delete=True`
- `metadata` is always a dict
- `provider` is always populated with the provider name
- provider-specific payload is optional and only exposed via `raw`
- unsupported operations fail with `ProviderCapabilityError`, not untyped backend errors

Fail certification if:

- a provider leaks backend-native record shapes into runtime/API/MCP
- a provider synthesizes success from ambiguous backend responses
- a provider leaks `KeyError`, `IndexError`, raw parser exceptions, or backend-specific exceptions

## 2. Capabilities

The provider must expose a complete `capabilities()` payload with all current fields:

- `supports_semantic_search`
- `supports_text_search`
- `supports_filters`
- `supports_metadata_filters`
- `supports_rerank`
- `supports_update`
- `supports_delete`
- `supports_pagination`
- `supports_scope_inventory`
- `supports_scopeless_list`
- `requires_scope_for_list`
- `requires_scope_for_search`
- `supports_owner_process_mode`

Capability rules:

- declared unsupported options must raise `ProviderCapabilityError`
- scope requirements must raise `ProviderScopeRequiredError`
- capabilities must describe real behavior, not desired future behavior

Examples:

- if `supports_rerank=False`, `search_memory(..., rerank=True)` must fail with `ProviderCapabilityError`
- if `requires_scope_for_search=True`, unscoped search must fail with `ProviderScopeRequiredError`
- if `supports_update=False`, `update_memory(...)` must fail with `ProviderCapabilityError`
- if `supports_delete=False`, `delete_memory(...)` must fail with `ProviderCapabilityError`
- if `supports_pagination=False`, non-null page cursors must fail with `ProviderCapabilityError`

## 3. Pagination and scope inventory

Providers that declare `supports_pagination=True` must implement stable cursor
pagination for `list_memories_page`. `search_memory_page` may also expose real
cursor behavior when the backend can preserve search ordering semantics across
pages.

The page shape is:

- `provider`
- `items`
- `next_cursor`
- `pagination_supported`

Rules:

- cursors are opaque provider-owned strings
- `next_cursor = None` means the walk is complete
- shared runtime layers must not inspect backend-private storage to emulate pagination
- providers without real cursor support may use the base single-page fallback, but must reject non-null cursors

Providers that declare `supports_scope_inventory=True` must keep the
AgentMemory-owned scope registry current on add/update/delete and make
`list_scopes` read from that registry. Legacy provider storage readers are
allowed only as explicit rebuild/migration seed paths, not as normal runtime
inventory hot paths.

Scope registry rules:

- primary provider storage is the source of truth
- registry writes are best-effort index syncs
- registry sync failures must mark provider-scoped degraded state instead of falsifying a successful primary write
- a successful rebuild or later successful sync clears degraded state
- partial records with no usable scope must not poison the registry

## 4. Error model

The provider must map backend failures into AgentMemory typed errors:

- `ProviderConfigurationError`
- `ProviderCapabilityError`
- `ProviderScopeRequiredError`
- `MemoryNotFoundError`
- `ProviderUnavailableError`
- `ProviderValidationError`

Use these rules:

- invalid or incomplete provider payloads -> `ProviderValidationError`
- unavailable backend/runtime/storage conditions -> `ProviderUnavailableError`
- missing records -> `MemoryNotFoundError`
- unsupported options -> `ProviderCapabilityError`
- missing required scope -> `ProviderScopeRequiredError`

The provider must fail closed on unexpected backend responses.

## 5. Required tests

### Reusable contract harness

Create a provider-specific test that subclasses `tests/provider_contract_harness.py`.

Minimum requirement:

- implement `create_provider(runtime_dir)`
- run the shared contract suite unchanged

Good pattern:

```python
import unittest

from my_provider import MyProvider
from provider_contract_harness import ProviderContractHarness


class MyProviderContractTests(ProviderContractHarness, unittest.TestCase):
    def create_provider(self, runtime_dir: str):
        return MyProvider(
            runtime_config={"runtime_dir": runtime_dir},
            provider_config=MyProvider.default_provider_config(runtime_dir=runtime_dir),
        )
```

### Provider-specific tests

Add focused tests for behavior that the shared harness does not prove:

- backend-specific normalization edge cases
- fail-closed handling of malformed backend payloads
- capability enforcement unique to that provider
- provider-specific config and health behavior
- pagination edge cases when `supports_pagination=True`
- scope registry sync/rebuild behavior when `supports_scope_inventory=True`
- unsupported update/delete behavior when those capabilities are false

## 6. Validation commands

Quick certification helper:

```powershell
agentmemory provider-certify --list
agentmemory provider-certify --list --json
agentmemory provider-certify <provider-name>
agentmemory provider-certify <provider-name> --json
agentmemory provider-certify <provider-name> --run-tests
agentmemory provider-certify <provider-name> --json --run-tests --summary-only
```

Examples:

```powershell
agentmemory provider-certify --list
agentmemory provider-certify localjson
agentmemory provider-certify localjson --json
agentmemory provider-certify localjson --run-tests
agentmemory provider-certify localjson --json --run-tests --summary-only
```

The helper uses an explicit certification registry with statuses such as:

- `certified`
- `provisional`
- `test-only`
- `unregistered` (fallback when a provider is not in the registry)

The helper reports:

- registry status
- whether the certification checklist is present
- related test modules
- whether a reusable harness consumer exists
- a final certification verdict
- a machine-readable `status_code`
- unmet requirements when the provider is not yet certifiable
- `test_summary` metrics in JSON mode when `--run-tests` is used
- `--summary-only` for compact CI-oriented output without the verbose test log

Use `--json` when you want machine-readable output for CI, scripts, or other maintainer tooling. The standalone `provider-certify` entrypoint remains available too.

Policy-level CI check:

```powershell
provider-certify-ci --json
```

Current expected policy targets:

- `localjson` -> `status_code=certified`
- `mem0` -> `status_code=certified_with_skips`

If a provider drops below its expected policy status, treat that as a certification regression.

Run the full suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

At minimum, review:

- the new provider harness test class
- `test_provider_contract_v1.py`
- transport mapping tests in `test_agentmemory_http_client.py` and `test_agentmemory_mcp_server.py`

If the provider is intended for real runtime use, also validate manually:

```powershell
agentmemory configure --provider <provider-name>
agentmemory doctor
agentmemory mcp-smoke
```

## 7. Certification exit criteria

A provider is certified for AgentMemory when:

- it passes the reusable provider contract harness
- it passes provider-specific edge-case tests
- it does not leak untyped exceptions through runtime/API/MCP/CLI
- its `capabilities()` match actual runtime behavior
- its normalization is fail-closed
- its documentation explains required config and notable limitations

If any of those are missing, the provider is experimental, not certified.
