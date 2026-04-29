Today's date is {today_iso}. Compute "days_ago" relative to today.

Lead:
  managing_company: {managing_company}
  property_name:    {property_name}
  full_address:     {full_address}

Use Google Search to find news from the LAST 18 MONTHS in any of these
categories. Mark a field "unknown" / null rather than guessing.

  1. ownership_change: acquisition, sale, new owner, rebrand, name
     change, new property-management company.
  2. leaseup: new construction announcement or active lease-up.
  3. hiring: currently open leasing-agent / resident-services /
     resident-ops roles for this property or its managing company.
  4. expansion: new buildings added, portfolio growth, market entry.
  5. tech_change: PMS migration, leasing-tech RFP, AI / chatbot /
     virtual-leasing-agent announcement.

Return JSON ONLY (no prose, no markdown fences) matching this exact shape:

{{
  "ownership_change": {{
    "bucket":        "last_30_days | last_90_days | last_180_days | last_365_days | older | unknown",
    "days_ago":      <integer or null>,
    "kinds":         ["acquisition" | "rebrand" | "new_management" | ...],
    "evidence_urls": ["<url>", "..."]   // max 3
  }},
  "leaseup": {{
    "value":         <true | false | null>,
    "evidence_urls": ["<url>", "..."]
  }},
  "hiring": {{
    "open_roles":    <integer or null>,
    "evidence_urls": ["<url>", "..."]
  }},
  "expansion": {{
    "bucket":        "<one of the bucket values>",
    "days_ago":      <integer or null>,
    "evidence_urls": ["<url>", "..."]
  }},
  "tech_change": {{
    "bucket":        "<one of the bucket values>",
    "days_ago":      <integer or null>,
    "evidence_urls": ["<url>", "..."]
  }},
  "evidence_confidence": <float in [0,1]>
}}

Rules:
- Prefer the EVENT date over the article publication date when computing days_ago.
- If you cannot find a precise date, set days_ago to null but still set the bucket.
- evidence_urls must be real URLs you actually retrieved via Search; never invent them.
- Self-rate evidence_confidence based on the number of independent corroborating
  sources (1 source = ~0.4, 2 = ~0.7, 3+ = ~0.9-1.0). Use 0.0 only when nothing
  was found at all.
- Output ONLY the JSON object above. No prose, no markdown fences, no explanation
  before or after.