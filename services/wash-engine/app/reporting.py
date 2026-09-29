def reconcile_session_credit(
    *,
    paid_sum: int,
    spent_sum: int,
    customer_saved_sum: int,
    final_credit_sum: int,
) -> dict[str, int]:
    """Reconcile session credit without treating stored-card turnover as revenue."""
    accounted_sum = spent_sum + customer_saved_sum + final_credit_sum
    return {
        "accounted_credit_sum": accounted_sum,
        "credit_difference_sum": paid_sum - accounted_sum,
    }
