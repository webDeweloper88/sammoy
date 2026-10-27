"""Persist local-card visit allowance alongside money, without storing card IDs.

The visit expires after 30 minutes on the card, as in the shared-wallet default.
Malformed saved data fails closed; expiry never changes the monetary balance.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math

KEY = 'local_pause_visits'
VISIT_MINUTES = 30


def allowance(value, limit):
    if type(value) not in (int, float) or not math.isfinite(value):
        return 0.0
    return min(max(0.0, float(limit)), max(0.0, float(value)))


def restore(metadata, kind, limit, now=None):
    now = now or datetime.now(timezone.utc)
    visits = metadata.get(KEY, {}) if isinstance(metadata, dict) else {}
    if not isinstance(visits, dict):
        return 0.0
    if kind not in visits:
        return max(0.0, float(limit))  # Existing cards before visit persistence.
    visit = visits[kind]
    try:
        expiry = datetime.fromisoformat(visit['expires_at'])
        if visit.get('schema') != 1 or expiry.tzinfo is None:
            return 0.0
        if now >= expiry:
            return max(0.0, float(limit))
        return allowance(visit['remaining_seconds'], limit)
    except (TypeError, ValueError, KeyError, AttributeError):
        return 0.0


def save(metadata, kind, remaining, limit, *, existing_balance=0, now=None):
    now = now or datetime.now(timezone.utc)
    result = deepcopy(metadata) if isinstance(metadata, dict) else {}
    visits = result.get(KEY)
    if not isinstance(visits, dict) or not existing_balance:
        visits = {}
    budget = allowance(remaining, limit)
    # Combining balances cannot replenish either live allowance.
    if existing_balance:
        budget = min(budget, restore(metadata, kind, limit, now))
    visits[kind] = {'schema': 1, 'remaining_seconds': budget,
                    'expires_at': (now + timedelta(minutes=VISIT_MINUTES)).isoformat()}
    result[KEY] = visits
    return result


def consume(metadata, kind):
    result = deepcopy(metadata) if isinstance(metadata, dict) else {}
    visits = result.get(KEY)
    if isinstance(visits, dict):
        visits.pop(kind, None)
        if not visits:
            result.pop(KEY, None)
    return result
