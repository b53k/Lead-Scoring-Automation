import math
from typing import Optional, Dict, Any

def clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(x, high))

def safe_float(x, default:  Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except (ValueError, TypeError):
        return default

def log_score(
    value: Optional[float],
    low: float,
    high: float,
    missing: float = 0.0,
) -> float:

    """
    Map a positive count-like variable to [0,1] using log scaling.
    low: value that should receive approximately 0
    high: value that should receive approximately 1

    Values above high saturate at 1.0
    """

    value = safe_float(value)
    if value is None or value < 0:
        return missing
    
    if high <= low:
        raise ValueError("high must be greater than low")

    numerator = math.log(1 + value) - math.log(1 + low)
    denominator = math.log(1 + high) - math.log(1 + low)

    return clamp(numerator / denominator)

def linear_score(
    value: Optional[float],
    low: float,
    high: float,
    missing: float = 0.0,
) -> float:

    """
    Map a value to [0,1] using linear scaling.
    Used for rates, percentages, and bounded quantities.
    """

    value = safe_float(value)
    if value is None:
        return missing
    
    if high <= low:
        raise ValueError("high must be greater than low")
    
    return clamp((value - low) / (high - low))

def boolean_score(value: Optional[bool], true_score: float = 1.0, false_score: float = 0.0) -> float:
    if value is None:
        return 0.0
    return true_score if value else false_score

# ================================ Account Fit =================================

PROPERTY_TYPES_SCORES = {
    "multifamily": 1.0,
    "student_housing": 1.0,
    "affordable_housing": 0.90,

    "senior_housing": 0.80,
    "single_family_home": 0.75,
    "commercial_office": 0.15,

    "hotel": 0.05,
    "unknown": 0.50
}


def account_fit(
    unit_count: Optional[int],
    manager_portfolio_size: Optional[int],
    property_type: Optional[str],
):
    """
    Returns account fit score in [0,1].

    unit_count: number of units at this property
    manager_portfolio_size: total units managed by the property manager (not just this property)
    property_type: normalized property type such as "multifamily", "student_housing", etc.
    """

    # A property becomes meaningfully interesting around 50-100 units.
    # 500+ units is very strong, but anything above that threshold should saturate.
    unit_score = log_score(unit_count, low = 20, high = 500, missing = 0.25)

    # A manager becomes meaningfully interesting around 200-20,000 units.
    portfolio_score = log_score(manager_portfolio_size, low = 200, high = 20000, missing = 0.25)

    normalized_type = (property_type or "unknown").strip().lower()
    type_score = PROPERTY_TYPES_SCORES.get(normalized_type, PROPERTY_TYPES_SCORES["unknown"])

    score = 0.45 * unit_score + 0.40 * portfolio_score + 0.15 * type_score

    return clamp(score)


# ================================ Operational Complexity ===============================
def operational_complexity(
    active_listings: Optional[int] = None,
    unit_count: Optional[int] = None,
    detected_pms_vendor: Optional[str] = None,
    floorplan_count: Optional[int] = None,
    review_count: Optional[int] = None,
    complaint_count: Optional[float] = None,
):
    """
    Returns operational complexity/pain score in [0,1].

    active_listings: number of visibly available units/listings
    unit_count: total number of units at the property
    complaint_rate: total reviews with 1 or 2 star ratings.
    """
    
    # Active listing score, if unit_count is known, use availability ratio. Else use a saturated score.
    if active_listings is not None and unit_count and unit_count > 0:
        availability_ratio = active_listings / unit_count

        # 0% available is not  leasing pressure.
        # 3-10% available is meaningful pressure.
        # >20% available is very strong leasing pressure.
        listing_score = linear_score(availability_ratio, low = 0.02, high = 0.20, missing = 0.0)
    else:
        listing_score = log_score(active_listings, low = 1, high = 30, missing = 0.0)

    # More floorplans means more complexity, but should saturate above 12.
    floorplan_score = log_score(floorplan_count, low = 1, high = 12, missing = 3.0)

    # PMS vendor detection implies software maturity and possible integration readiness.
    pms_score = 1.0 if detected_pms_vendor else 0.0

    # Review volume indicates resident/prospect interaction volume.
    review_volume_score = log_score(review_count, low = 10, high = 500, missing = 0.0)
    
    # Complaint rate should matter only if there are enough reviews.
    if review_count and review_count > 0:
        complaint_score = linear_score(complaint_count/review_count, low = 0.05, high = 0.40, missing = 0.0)
    else:
        complaint_score = 0.0
        
    review_pain_score = review_volume_score * complaint_score

    score = 0.30 * listing_score + 0.15 * floorplan_score + 0.15 * pms_score + 0.3 * review_pain_score

    return clamp(score)

# ================================ Buying Trigger ===============================

def recency_score(
    days_ago: Optional[int] = None,
    bucket: Optional[str] = None,
    half_life_days: int = 180,
) -> float:
    """
    Prefer exact days when available, otherwise fall back to a bucket.
    """
    if days_ago is not None and days_ago >= 0:
        return math.exp(-math.log(2) * days_ago / half_life_days)
    if bucket:
        return RECENCY_BUCKETS.get(bucket.strip().lower(), 0.0)
    return 0.0

RECENCY_BUCKETS = {
    "last_30_days":   1.00,
    "last_90_days":   0.85,
    "last_180_days":  0.65,
    "last_365_days":  0.40,
    "older":          0.10,
    "unknown":        0.00,
}

RECENCY_LABELS = {
    "last_30_days":  "in the last 30 days",
    "last_90_days":  "in the last 3 months",
    "last_180_days": "in the last 6 months",
    "last_365_days": "in the last year",
    "older":         "over a year ago",
    "unknown":       None,
}

KIND_LABELS = {
    "acquisition":    "acquisition",
    "sale":           "sale",
    "rebrand":        "rebrand",
    "new_management": "new property-management company",
    "new_owner":      "new owner",
    "name_change":    "name change",
}

def _recency_phrase(bucket: Optional[str], days_ago: Optional[int]) -> Optional[str]:
    """Pick the most informative phrase: exact days when known, else bucket label."""
    d = safe_float(days_ago)
    if d is not None and d >= 0:
        if d <= 7:    return f"{int(d)} days ago"
        if d <= 30:   return f"~{int(d)} days ago"
        if d <= 60:   return "~1 month ago"
        if d <= 365:  return f"~{int(round(d / 30))} months ago"
        return "over a year ago"
    if bucket:
        return RECENCY_LABELS.get(bucket.strip().lower())
    return None


def _join_kinds(kinds) -> Optional[str]:
    """['acquisition', 'rebrand', 'new_management'] -> 'acquisition, rebrand and new property-management company'"""
    if not kinds:
        return None
    if isinstance(kinds, str):
        kinds = [kinds]
    labels = [KIND_LABELS.get((k or "").strip().lower(), (k or "").replace("_", " "))
              for k in kinds if k]
    labels = [l for l in labels if l]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def buying_trigger(

    # 1. Ownership/control change
    # (acquisition + rebrand + new management -> collapsed into one axis)
    ownership_change_bucket: Optional[str] = None,
    ownership_change_days_ago: Optional[int] = None,
    ownership_change_kinds: Optional[list[str]] = None,
    
    # 2. New supply pressure 
    in_leaseup_or_new_construction: Optional[bool] = None,

    # 3. Hiring momentum - a count not a boolean
    open_leasing_or_ops_roles: Optional[int] = None,

    # 4. Portfolio expansion
    expansion_bucket: Optional[str] = None,
    expansion_days_ago: Optional[int] = None,

    # 5. Tech-stack change (PMS migration, AI rollout, etc.)
    tech_change_bucket: Optional[str] = None,
    tech_change_days_ago: Optional[int] = None,

    # 6. LLM's self-rated evidence quality from the web-search 
    evidence_confidence: float = 1.0,
) -> float:

    """
    Returns buying trigger score in [0, 1].
    """

    ownership_score = recency_score(
        days_ago=ownership_change_days_ago,
        bucket=ownership_change_bucket,
        half_life_days=240,
    )
    if ownership_change_kinds:
        kinds = {k.strip().lower() for k in ownership_change_kinds}
        # Capped bonus: 1 kind -> x1.0, 2 -> x1.10, 3 -> x1.20.
        ownership_score = clamp(ownership_score * (1.0 + 0.10 * (len(kinds) - 1)))
    
    leaseup_score = boolean_score(in_leaseup_or_new_construction)
    
    # 0 -> 0, 1 -> meaningful, 5+ -> saturated
    
    hiring_score = log_score(open_leasing_or_ops_roles, low=0, high=5, missing=0.0)
    
    expansion_score = recency_score(
        days_ago=expansion_days_ago,
        bucket=expansion_bucket,
        half_life_days=240,
    )
    tech_change_score = recency_score(
        days_ago=tech_change_days_ago,
        bucket=tech_change_bucket,
        half_life_days=180,
    )
    
    score = (
        0.30 * ownership_score
        + 0.20 * leaseup_score
        + 0.20 * hiring_score
        + 0.15 * expansion_score
        + 0.15 * tech_change_score
    )

    return clamp(score * clamp(evidence_confidence, 0.0, 1.0))


# ================================ Market Context ===============================

def market_context(census_data: Dict[str, Any]) -> float:
    """
    Returns market context score in [0, 1].

    Census data should contain:
        total_housing_units
        population
        median_household_income
        employment_rate
        occupancy_rate

    employment_rate and occupancy_rate should be in [0, 1].
    """

    housing_units = safe_float(census_data['total_housing_units'])
    population = safe_float(census_data['population'])
    median_income = safe_float(census_data['median_household_income'])
    employment_rate = safe_float(census_data['employment_rate']/100.0)
    occupancy_rate = safe_float(census_data['occupancy_rate']/100.0)

    # Zipcode-level housing scale.
    # 2k housing units is small/moderate
    # 25k housing units is a large local housing market.
    housing_score = log_score(housing_units, low=2_000, high=25_000, missing=0.0)

    # Zipcode-level population.
    # 10k is modest
    # 75k+ is a large zipcode level population.
    population_score = log_score(population, low=10_000, high=75_000, missing=0.0)

    # Median income.
    # Use a bounded linear range.
    # Below 45k gets low score, above 150k saturates.
    income_score = linear_score(median_income, low=45_000, high=150_000, missing=0.0)

    # Employment rate.
    # Most reasonable ZIPs will be around 0.90-0.98.
    # Values outside this range should not dominate.
    employment_score = linear_score(employment_rate, low=0.88, high=0.97, missing=0.0)

    # Occupancy rate.
    # For resident-service volume, high occupancy is good.
    # But do not over-penalize lower occupancy because that may indicate leasing pressure.
    occupancy_score = linear_score(occupancy_rate, low=0.85, high=0.98, missing=0.0)

    score = 0.30 * housing_score + 0.20 * population_score + 0.20 * income_score + 0.15 * employment_score + 0.15 * occupancy_score

    return clamp(score)


# ================================ Data Confidence ===============================

def data_confidence(
    census_data: Dict[str, Any] = None,
    property_website_found: Optional[bool] = None,
    api_success_count: Optional[int] = None,
    api_attempt_count: Optional[int] = None,
) -> float:
    
    """
    Returns data confidence score in [0, 1].

    Combines three signals:
    * Census data presence - how many demogrpahic fields are populated.
    * Property website found - gates downstream PMS / listings enrichment.
    * API success rate - how many enrichment calls came back cleanly.

    Low confidence routes the lead to "Needs Review" priority bucket.
    """
    
    expected_census_keys = (
        "total_housing_units",
        "population",
        "median_household_income",
        "employment_rate",
        "occupancy_rate",
    )
    present = sum(1 for k in expected_census_keys if census_data.get(k) not in (None, 0.0))
    census_score = present / len(expected_census_keys)

    website_score = boolean_score(property_website_found)
    
    if api_attempt_count and api_attempt_count > 0:
        api_score = clamp((api_success_count or 0) / api_attempt_count)
    else:
        api_score = 0.0

    score = 0.5 * census_score + 0.1 * website_score + 0.4 * api_score

    return clamp(score)



# ================================ Lead Score ===============================

def lead_score(
    account_fit_score: float,
    operational_complexity_score: float,
    buying_trigger_score: float,
    market_context_score: float,
    data_confidence_score: float,
) -> float:
    """
    Returns lead score in [0, 1].
    """
    
    score = (
        0.35 * clamp(account_fit_score)
        + 0.25 * clamp(operational_complexity_score)
        + 0.20 * clamp(buying_trigger_score)
        + 0.10 * clamp(market_context_score)
        + 0.10 * clamp(data_confidence_score)
    )

    return round(clamp(score), 4)


def priority_bucket(score: float, data_confidence: float) -> str:
    """
    Converts score into a sales-friendly priority bucket.
    """

    if data_confidence < 0.4:
        return "Needs Review"
    
    if score >= 0.80:
        return "High"
    elif score >= 0.60:
        return "Medium"
    elif score >= 0.40:
        return "Low"
    else:
        return "Needs Review"


def generate_reason(
    unit_count=None,
    manager_portfolio_size=None,
    property_type=None,
    active_listings=None,
    detected_pms_vendor=None,

    ownership_change_bucket=None,
    ownership_change_days_ago=None,
    ownership_change_kinds=None,
    expansion_bucket=None,
    expansion_days_ago=None,
    evidence_confidence=None,

    census_data=None,
) -> list[str]:
    """
    Generates human-readable reason codes explaining *why* this lead scored
    the way it did. These are designed to be dropped directly into an SDR's
    talking points or a draft outreach email.

    Every block is independently None-guarded so partial enrichment still
    produces useful output.
    """

    reasons: list[str] = []

    # -------- Account fit --------
    uc = safe_float(unit_count)
    if uc is not None:
        if uc >= 500:
            reasons.append(
                f"Large property with ~{int(uc)} units — strong fit for "
                "EliseAI's high-volume leasing automation."
            )
        elif uc >= 100:
            reasons.append(
                f"Mid-sized property (~{int(uc)} units) — typical EliseAI "
                "sweet spot."
            )
        elif uc >= 20:
            reasons.append(
                f"Smaller property (~{int(uc)} units) — fit is stronger if "
                "it's part of a larger portfolio."
            )

    ps = safe_float(manager_portfolio_size)
    if ps is not None and ps >= 1000:
        reasons.append(
            f"Manager operates a sizable portfolio (~{int(ps):,} units) — "
            "multi-property expansion potential."
        )

    if property_type:
        ptype = property_type.strip().lower()
        pretty = ptype.replace("_", " ")
        if ptype in ("multifamily", "student_housing", "affordable_housing", "senior_housing", "single_family_home"):
            reasons.append(
                f"Property type '{pretty}' aligns directly with EliseAI's core ICP."
            )
        elif ptype in ("commercial_office", "hotel"):
            reasons.append(
                f"Property type '{pretty}' is outside EliseAI's typical ICP "
                "— qualify carefully."
            )

    # -------- Operational complexity --------
    al = safe_float(active_listings)
    if al is not None and al >= 10:
        reasons.append(
            f"~{int(al)} active listings — meaningful leasing pressure that "
            "EliseAI shortens with 24/7 prospect follow-up."
        )

    if detected_pms_vendor:
        reasons.append(
            f"Detected PMS vendor: {detected_pms_vendor} — existing software "
            "budget and a clear integration path."
        )

    # -------- Buying trigger --------
    MIN_TRIGGER_CONFIDENCE = 0.4
    ec = safe_float(evidence_confidence) or 0.0

    if ec >= MIN_TRIGGER_CONFIDENCE:

        #1. Ownership/control change
        when = _recency_phrase(ownership_change_bucket, ownership_change_days_ago)
        if when:
            kinds_phrase = _join_kinds(ownership_change_kinds)
            if kinds_phrase:
                reasons.append(
                    f"Recent {kinds_phrase} {when} — strong buying trigger; "
                    "new ownership/management typically re-evaluates the leasing "
                    f"tech stack (evidence confidence {ec:.2f})."
                )
            else:
                reasons.append(
                    f"Ownership/control change {when} — buying trigger; "
                    f"expect tech-stack re-evaluation (evidence confidence {ec:.2f})."
                )

        
        # 2. Portfolio expansion
        when = _recency_phrase(expansion_bucket, expansion_days_ago)
        if when:
            reasons.append(
                f"Manager portfolio expanded {when} — growth phase, "
                "often paired with tooling investment."
            )

    elif ec > 0:
        reasons.append(
            f"Some buying-trigger signals present but evidence confidence "
            f"is low ({ec:.2f}); recommend manual verification before outreach."
        )

    # -------- Market context (census values are percentages, not proportions) --------
    if isinstance(census_data, dict) and census_data:
        income = safe_float(census_data.get("median_household_income"))
        if income is not None and income >= 100_000:
            reasons.append(
                f"Affluent ZIP (median household income ~${int(income):,}) — "
                "supports premium rents and resident-experience investments."
            )

        pop = safe_float(census_data.get("population"))
        if pop is not None and pop >= 50_000:
            reasons.append(
                f"Dense ZIP (~{int(pop):,} residents) — high prospect inflow "
                "amplifies the value of automated leasing."
            )

        occ = safe_float(census_data.get("occupancy_rate"))
        if occ is not None:
            if occ >= 95:
                reasons.append(
                    f"Very high local occupancy ({occ:.1f}%) — turnover-driven "
                    "leasing windows are short; speed matters."
                )
            elif occ < 85:
                reasons.append(
                    f"Lower local occupancy ({occ:.1f}%) — suggests leasing "
                    "pressure where EliseAI can lift conversion."
                )

    if not reasons:
        reasons.append(
            "Insufficient enriched data — recommend manual review before outreach."
        )

    return reasons


def get_lead_info(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns lead information in a structured format.
    """

    account_fit_score = account_fit(
        unit_count=features.get("unit_count"),
        manager_portfolio_size=features.get("manager_portfolio_size"),
        property_type=features.get("property_type"),
    )

    operational_complexity_score = operational_complexity(
        active_listings=features.get("active_listings"),
        unit_count=features.get("unit_count"),
        detected_pms_vendor=features.get("detected_pms_vendor"),
        floorplan_count=features.get("floorplan_count"),
        review_count=features.get("review_count"),
        complaint_count=features.get("complaint_count"),
    )

    buying_trigger_score = buying_trigger(
        ownership_change_bucket=features.get("ownership_change_bucket"),
        ownership_change_days_ago=features.get("ownership_change_days_ago"),
        ownership_change_kinds=features.get("ownership_change_kinds"),
        in_leaseup_or_new_construction=features.get("in_leaseup_or_new_construction"),
        open_leasing_or_ops_roles=features.get("open_leasing_or_ops_roles"),
        expansion_bucket=features.get("expansion_bucket"),
        expansion_days_ago=features.get("expansion_days_ago"),
        tech_change_bucket=features.get("tech_change_bucket"),
        tech_change_days_ago=features.get("tech_change_days_ago"),
        evidence_confidence=features.get("evidence_confidence"),
    )

    market_context_score = market_context(features.get("census_data"))

    data_confidence_score = data_confidence(
        census_data=features.get("census_data"),
        property_website_found=features.get("property_website_found"),
        api_success_count=features.get("api_success_count"),
        api_attempt_count=features.get("api_attempt_count"),
    )

    final_score = lead_score(
        account_fit_score=account_fit_score,
        operational_complexity_score=operational_complexity_score,
        buying_trigger_score=buying_trigger_score,
        market_context_score=market_context_score,
        data_confidence_score=data_confidence_score,
    )

    return {
        "lead_score": final_score,
        
        "priority_bucket": priority_bucket(final_score, data_confidence_score),

        "score_breakdown": {
            "account_fit": round(account_fit_score, 4),
            "operational_complexity": round(operational_complexity_score, 4),
            "buying_trigger": round(buying_trigger_score, 4),
            "market_context": round(market_context_score, 4),
            "data_confidence": round(data_confidence_score, 4),
        },

        "reason_codes": generate_reason(
            unit_count=features.get("unit_count"),
            manager_portfolio_size=features.get("manager_portfolio_size"),
            property_type=features.get("property_type"),
            active_listings=features.get("active_listings"),
            detected_pms_vendor=features.get("detected_pms_vendor"),


            ownership_change_bucket=features.get("ownership_change_bucket"),
            ownership_change_days_ago=features.get("ownership_change_days_ago"),
            ownership_change_kinds=features.get("ownership_change_kinds"),
            expansion_bucket=features.get("expansion_bucket"),
            expansion_days_ago=features.get("expansion_days_ago"),
            evidence_confidence=features.get("evidence_confidence"),


            census_data=features.get("census_data"),
        ),
    }