"""Account-period comparisons. Missing evidence is not a zero baseline."""
import math


def summary(data):
    k = data.get('kpis', {})
    rows = data.get('accountDailySeries', [])
    items = data.get('items', [])
    units = k.get('units')
    revenue = k.get('revenue')
    visits_known = bool(items) and all(x.get('visitsCoverageComplete') is True for x in items)
    values = {key: k.get(key) for key in (
        'revenue', 'units', 'adsRevenue', 'organicRevenue', 'investment',
        'tacosBaseRevenue', 'tacos', 'roas', 'adsNoSales', 'investmentNoAdsSales')}
    values.update(
        orders=sum(x.get('orders', 0) for x in items) if items else None,
        price=revenue / units if revenue is not None and units else None,
        visits=sum(x.get('visits', 0) for x in rows) if visits_known else None,
        cancelledOrders=None,  # Returns and line-item orders do not establish cancellations.
        returnsAmount=k.get('returnsAmount') if k.get('returnsAvailable') else None,
        returnsOrdersCount=k.get('returnsOrdersCount') if k.get('returnsAvailable') else None,
    )
    for metric in ('visits', 'cancelledOrders'):
        official = data.get('accountMetrics', {}).get(metric, {})
        if official.get('complete') is True:
            values[metric] = official.get('total')
    return values


def compare(current, previous, *, verified):
    result = {}
    for key, value in current.items():
        old = previous.get(key)
        proven = verified.get(key, False) if isinstance(verified, dict) else verified
        available = proven and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (value, old))
        status = 'available' if available else 'unavailable'
        change = None
        if available:
            if old == 0:
                status = 'zero_baseline' if value != 0 else 'available'
                change = 0 if value == 0 else None
            else:
                change = (value - old) / abs(old)
        result[key] = dict(current=value, previous=old, change=change, status=status)
    return result
