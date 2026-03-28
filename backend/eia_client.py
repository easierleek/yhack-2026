# ============================================================
#  NEO — Nodal Energy Oracle
#  eia_client.py  —  EIA API Integration
#  YHack 2025
#
#  ROLE: Data & Dashboard Engineer owns this file.
#
#  Pulls two live data points from the U.S. Energy Information
#  Administration (EIA) API v2 and blends them into a single
#  $/kWh market price that the AI brain uses every control cycle.
#
#    1. Retail price   — latest monthly avg (cents/kWh → $/kWh)
#    2. RTO demand     — latest hourly CONUS grid demand (MW)
#
#  Both values are cached for 5 minutes so we don't hammer the
#  free-tier API during the 100 ms control loop.
#
#  If the API is unreachable the module falls back to a purely
#  simulated price so the rest of the system keeps running.
#
#  EIA API docs: https://www.eia.gov/opendata/documentation.php
#  Register for a free key: https://www.eia.gov/opendata/
# ============================================================

import math
import time
import threading
import requests

# ─── CREDENTIALS ─────────────────────────────────────────────────────────────
# Set your key here OR export it as the env-var EIA_API_KEY before running.
import os
EIA_API_KEY: str = os.environ.get("EIA_API_KEY", "YOUR_EIA_KEY_HERE")
EIA_BASE_URL: str = "https://api.eia.gov/v2"

# ─── CACHE ───────────────────────────────────────────────────────────────────
CACHE_TTL_SECONDS = 300   # refresh every 5 minutes

_cache_lock = threading.Lock()
_cache: dict = {
    # retail price in $/kWh  (EIA reports cents/kWh → we divide by 100)
    "retail_usd_per_kwh": 0.17,   # US average fallback
    # latest hourly CONUS demand in MW
    "demand_mw": 400_000.0,       # mid-range fallback
    # unix timestamp of last successful fetch
    "fetched_at": 0.0,
    # True when at least one live fetch has succeeded
    "live": False,
}

# Approximate CONUS (US-48) summer peak for demand normalisation
_US48_PEAK_MW = 700_000.0

# ─── EIA FETCH HELPERS ───────────────────────────────────────────────────────

def _get(path: str, params: dict, timeout: float = 6.0) -> dict:
    """Thin wrapper around requests.get with error surfacing."""
    params["api_key"] = EIA_API_KEY
    resp = requests.get(f"{EIA_BASE_URL}{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_retail_price() -> float:
    """
    Returns the latest monthly US average retail electricity price in $/kWh.

    EIA endpoint:
        /v2/electricity/retail-sales/data/
        frequency = monthly
        data[0]   = price  (cents / kWh)

    No state or sector facets are applied — the EIA API rejects "US" as a
    stateid and "all sectors" as a sectorName.  Instead we pull the 20 most
    recent monthly rows across all states and sectors, filter out nulls, and
    return the mean.  This gives a robust national average regardless of which
    specific state/sector rows the API happens to return first.
    """
    js = _get(
        "/electricity/retail-sales/data/",
        {
            "frequency":          "monthly",
            "data[0]":            "price",
            "sort[0][column]":    "period",
            "sort[0][direction]": "desc",
            "length":             "20",
        },
    )
    rows = js["response"]["data"]
    prices = [
        float(r["price"])
        for r in rows
        if r.get("price") is not None and float(r["price"]) > 0
    ]
    if not prices:
        raise ValueError("EIA returned no valid price rows")
    avg_cents = sum(prices) / len(prices)
    return avg_cents / 100.0   # cents/kWh -> $/kWh


def _fetch_rto_demand() -> float:
    """
    Returns the latest hourly CONUS grid demand in MW.

    EIA endpoint:
        /v2/electricity/rto/region-data/data/
        frequency       = hourly
        data[0]         = value      (MW)
        type            = D          (Demand)
        respondent      = US48       (contiguous US)
    """
    js = _get(
        "/electricity/rto/region-data/data/",
        {
            "frequency":              "hourly",
            "data[0]":                "value",
            "facets[type][]":         "D",
            "facets[respondent][]":   "US48",
            "sort[0][column]":        "period",
            "sort[0][direction]":     "desc",
            "length":                 "1",
        },
    )
    return float(js["response"]["data"][0]["value"])


# ─── CACHE REFRESH ───────────────────────────────────────────────────────────

def _maybe_refresh_cache() -> None:
    """
    Refreshes the cache in the calling thread if TTL has expired.
    Thread-safe via _cache_lock.  Non-blocking for callers: if the lock
    is already held by another refresh, we skip and use the stale value.
    """
    now = time.time()

    # Fast path — still fresh, no lock needed for read
    if now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return

    acquired = _cache_lock.acquire(blocking=False)
    if not acquired:
        return  # another thread is already refreshing

    try:
        # Double-check inside the lock
        if now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
            return

        errors = []

        try:
            price = _fetch_retail_price()
            _cache["retail_usd_per_kwh"] = price
        except Exception as exc:
            errors.append(f"retail_price: {exc}")

        try:
            demand = _fetch_rto_demand()
            _cache["demand_mw"] = demand
        except Exception as exc:
            errors.append(f"rto_demand: {exc}")

        if errors:
            print(f"[EIA] Partial refresh errors: {'; '.join(errors)}")
        else:
            _cache["live"] = True
            print(
                f"[EIA] Cache refreshed — "
                f"retail={_cache['retail_usd_per_kwh']:.4f} $/kWh  "
                f"demand={_cache['demand_mw']:,.0f} MW"
            )

        _cache["fetched_at"] = time.time()

    finally:
        _cache_lock.release()


# ─── TIME-OF-DAY SURGE CURVE ─────────────────────────────────────────────────
# Mirrors the duck curve used by the AI but expressed as a price multiplier.
# Hours are simulated hours (0-23), not wall-clock hours.

def _tod_multiplier(sim_hour: float) -> float:
    """
    Returns a time-of-day price surge multiplier:
        Night  (00-05):  0.50  (off-peak, super cheap)
        Morning(07-09):  2.50  (breakfast demand spike)
        Evening(18-21):  3.00  (peak evening demand)
        Otherwise:       1.00  (shoulder)
    Linearly interpolated at the transitions to avoid hard steps.
    """
    h = sim_hour % 24.0

    # Night valley
    if 0.0 <= h < 5.0:
        return 0.50

    # Ramp up from night → morning  (05:00 – 07:00)
    if 5.0 <= h < 7.0:
        return 0.50 + (h - 5.0) / 2.0 * (2.50 - 0.50)

    # Morning peak plateau
    if 7.0 <= h < 9.0:
        return 2.50

    # Ramp down from morning → shoulder  (09:00 – 10:00)
    if 9.0 <= h < 10.0:
        return 2.50 - (h - 9.0) * (2.50 - 1.00)

    # Shoulder
    if 10.0 <= h < 17.0:
        return 1.00

    # Ramp up from shoulder → evening peak  (17:00 – 18:00)
    if 17.0 <= h < 18.0:
        return 1.00 + (h - 17.0) * (3.00 - 1.00)

    # Evening peak
    if 18.0 <= h < 21.0:
        return 3.00

    # Ramp down from evening → night  (21:00 – 23:59)
    return 3.00 - (h - 21.0) / 3.0 * (3.00 - 0.50)


# ─── PUBLIC API ──────────────────────────────────────────────────────────────

def get_market_price(sim_hour: float) -> float:
    """
    Returns the blended electricity market price in $/kWh, clamped 0.50–3.00.

    Blending formula
    ----------------
    1. Base price    = EIA retail $/kWh  (live or cached)
    2. Demand boost  = base × (current_demand / peak_demand)
                       → pushes price up when the real US grid is stressed
    3. ToD surge     = (base + demand_boost) × tod_multiplier(sim_hour)
    4. Noise wave    = ±0.10 slow sine  (simulates intra-hour spot volatility)
    5. Clamp to [0.50, 3.00] to keep penalty maths sane

    Parameters
    ----------
    sim_hour : float
        Current simulated hour (0.0 – 23.9).

    Returns
    -------
    float  — market price in $/kWh, rounded to 2 dp.
    """
    _maybe_refresh_cache()

    retail   = _cache["retail_usd_per_kwh"]   # e.g. 0.17
    demand   = _cache["demand_mw"]             # e.g. 420_000

    # Demand-stress factor: how loaded is the real grid right now?
    # Typically 0.40 – 0.90; spikes toward 1.0 on hot summer afternoons.
    demand_factor = min(demand / _US48_PEAK_MW, 1.0)   # 0.0 – 1.0

    # Step 1 & 2 — demand-adjusted base
    adjusted_base = retail * (1.0 + demand_factor)   # e.g. 0.17 × 1.6 = 0.27

    # Step 3 — scale to sim price range
    # US average retail 0.17 $/kWh maps to mid-range "1.0" in our 0.5-3.0 scale.
    # tod_multiplier already encodes the 0.5 – 3.0 range so we normalise:
    normalised = (adjusted_base / 0.17) * _tod_multiplier(sim_hour)

    # Step 4 — slow volatility noise
    noise = math.sin(time.time() * 0.07) * 0.10

    price = normalised + noise
    return round(max(0.50, min(3.00, price)), 2)


def get_cache_status() -> dict:
    """
    Returns a snapshot of the current cache for dashboard display.

    Example output:
        {
            "retail_usd_per_kwh": 0.1723,
            "demand_mw": 421500.0,
            "live": True,
            "age_seconds": 47.3
        }
    """
    age = time.time() - _cache["fetched_at"]
    return {
        "retail_usd_per_kwh": round(_cache["retail_usd_per_kwh"], 4),
        "demand_mw":          round(_cache["demand_mw"], 0),
        "live":               _cache["live"],
        "age_seconds":        round(age, 1),
    }


def warm_cache() -> None:
    """
    Call once at startup to pre-populate the cache before the control loop
    starts.  Blocks until the first fetch attempt completes (or times out).
    """
    print("[EIA] Warming cache...")
    # Force expiry so _maybe_refresh_cache will actually fetch
    _cache["fetched_at"] = 0.0
    # Re-acquire blocking this time (startup is fine to wait)
    _cache_lock.acquire(blocking=True)
    try:
        errors = []
        try:
            _cache["retail_usd_per_kwh"] = _fetch_retail_price()
        except Exception as exc:
            errors.append(f"retail_price: {exc}")

        try:
            _cache["demand_mw"] = _fetch_rto_demand()
        except Exception as exc:
            errors.append(f"rto_demand: {exc}")

        _cache["fetched_at"] = time.time()

        if errors:
            print(f"[EIA] Warm-up partial failure (fallback values in use): {'; '.join(errors)}")
        else:
            _cache["live"] = True
            status = get_cache_status()
            print(
                f"[EIA] Cache warm — "
                f"retail={status['retail_usd_per_kwh']:.4f} $/kWh  "
                f"demand={status['demand_mw']:,.0f} MW"
            )
    finally:
        _cache_lock.release()


# ─── QUICK SELF-TEST ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running EIA client self-test...\n")
    warm_cache()

    print("\nSample prices across the simulated day:")
    for hour in [0, 3, 6, 7, 9, 12, 17, 18, 20, 22]:
        p = get_market_price(float(hour))
        bar = "█" * int(p * 6)
        print(f"  {hour:02d}:00  ${p:.2f}/kWh  {bar}")

    print("\nCache status:", get_cache_status())
