"""
Tests for Anti-Bloat Auditor: Trust Boundary enforcement and Fail-Fast principle.
"""

from sentinel.agents.anti_bloat import analyze_symbol_anti_bloat
from sentinel.state import ASTSymbolScope, FindingCategory, TrustZone


def test_ghost_null_check_flagged_in_internal_core():
    code = """def calculate_total(order: Order) -> float:
    if order is None:
        return 0.0
    return order.total
"""
    symbol = ASTSymbolScope(
        symbol_name="calculate_total",
        symbol_type="function",
        file_path="domain/orders.py",
        start_line=1,
        end_line=4,
        code_snippet=code,
        trust_zone=TrustZone.INTERNAL_CORE,
    )

    findings = analyze_symbol_anti_bloat(symbol)
    assert len(findings) == 1
    assert findings[0].category == FindingCategory.ANTI_BLOAT
    assert "Ghost Null-Check" in findings[0].title


def test_perimeter_validation_not_flagged():
    """Defensive validation at perimeter must be preserved and never flagged as bloat."""
    code = """def handle_request(request: Request):
    if request is None:
        return None
    return request.body
"""
    symbol = ASTSymbolScope(
        symbol_name="handle_request",
        symbol_type="function",
        file_path="api/v1/webhook.py",
        start_line=1,
        end_line=4,
        code_snippet=code,
        trust_zone=TrustZone.PERIMETER,
    )

    findings = analyze_symbol_anti_bloat(symbol)
    assert len(findings) == 0


def test_pokemon_exception_swallowing_flagged():
    code = """def process_event(event):
    try:
        dispatch(event)
    except Exception:
        pass
"""
    symbol = ASTSymbolScope(
        symbol_name="process_event",
        symbol_type="function",
        file_path="services/event_bus.py",
        start_line=1,
        end_line=5,
        code_snippet=code,
        trust_zone=TrustZone.INTERNAL_CORE,
    )

    findings = analyze_symbol_anti_bloat(symbol)
    assert len(findings) == 1
    assert "Silent Error Swallowing" in findings[0].title
