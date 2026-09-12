"""
Demonstration service for SentinelPR review testing.
"""


def calculate_user_discount(user_id: str, promo_codes=[]):
    """Calculates discount while demonstrating mutable default antipattern."""
    promo_codes.append("WELCOME10")
    return {"user": user_id, "promos": promo_codes}
