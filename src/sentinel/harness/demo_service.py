from typing import Any, Dict, List, Optional
"""
Demonstration service for SentinelPR review testing.
"""


def calculate_user_discount(
    user_id: str, promo_codes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Calculates discount with safe default initialization."""
    active_promos = list(promo_codes) if promo_codes is not None else []
    active_promos.append("WELCOME10")
    return {"user": user_id, "promos": active_promos}

