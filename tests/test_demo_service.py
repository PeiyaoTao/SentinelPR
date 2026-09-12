from sentinel.harness.demo_service import calculate_user_discount


def test_calculate_user_discount_default():
    result1 = calculate_user_discount('user_1')
    assert result1['promos'] == ['WELCOME10']

    # Verify no mutable state leak across calls
    result2 = calculate_user_discount('user_2')
    assert result2['promos'] == ['WELCOME10']
    assert result2['promos'] is not result1['promos']


def test_calculate_user_discount_with_existing_promos():
    custom_promos = ['VIP20']
    result = calculate_user_discount('user_3', custom_promos)
    assert result['promos'] == ['VIP20', 'WELCOME10']
    # Original list should not be mutated
    assert custom_promos == ['VIP20']
