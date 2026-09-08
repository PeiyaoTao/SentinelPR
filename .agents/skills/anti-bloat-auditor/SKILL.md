---
name: anti-bloat-auditor
description: Skill for detecting overprotective defensive code, ghost null-checks, and redundant error handling according to the Trust Boundary Matrix.
---

# Anti-Bloat Auditor Skill

## Purpose
The Anti-Bloat Auditor identifies over-defensive programming practices that clutter the codebase, mask underlying contract bugs, and violate the Fail-Fast Principle.

## Detection Patterns

### 1. Ghost Null-Checks (`INTERNAL_CORE`)
- **Antipattern**:
  ```python
  def calculate_tax(order: Order) -> Decimal:
      if order is None:  # Ghost check: Order is non-optional and guaranteed by upstream caller
          return Decimal(0)
      return order.total * Decimal("0.08")
  ```
- **Correction**: Trust the type contract and upstream boundary. If `order` can never be `None`, remove the check or use an explicit precondition assertion.

### 2. Pokemon Exception Handling (`try...except Exception: pass`)
- **Antipattern**:
  ```python
  try:
      cache.set(key, value)
  except Exception:
      pass  # Silent failure obscures connection drops or serialization bugs
  ```
- **Correction**: Catch specific, anticipated exceptions (e.g., `RedisConnectionError`) or log with warning and surface the metric.

### 3. Redundant Layer Validation
- **Antipattern**:
  Re-validating email format or UUID structure inside deep domain repositories when already validated by Pydantic models at the API perimeter.

## Trust Boundary Enforcement
- **DO NOT** flag defensive checks in `PERIMETER` code (controllers, request handlers, public webhooks, CLI arguments).
- **DO** flag redundant defensive checks in `INTERNAL_CORE` domain logic.
