import os
import time
from typing import Iterable, Dict, Any, Optional

import pandas as pd
from geopy.geocoders import Nominatim

from clients import lead_cache
from domain.scoring import get_lead_info
from services.feature_pipeline import FeaturePipeline
from services.email_drafter import draft_outreach_email
from clients.census_client import get_census_data_w_zipcode_fallback


def _resolve_zipcode(full_address: str, zipcode: Any) -> Any:
    if pd.notna(zipcode) and str(zipcode).strip():
        return zipcode
    try:
        time.sleep(0.05)
        loc = Nominatim(user_agent="elise_gtm", timeout=5).geocode(
            full_address, addressdetails=True
        )
        if loc:
            return loc.raw.get("address", {}).get("postcode")
    except Exception:
        pass
    return None


def process_row(row: pd.Series, force_fresh_llm: bool = False) -> Dict[str, Any]:
    property_name    = row["Property Name"]
    property_address = row["Property Address"]
    city             = row["City"]
    state            = row["State"]
    country          = row["Country"]
    zipcode          = row.get("Zipcode")


    full_address = ", ".join([str(property_address), str(city), str(state), str(country)])
    zipcode = _resolve_zipcode(full_address, zipcode)


    census_data = None
    if zipcode is not None and str(zipcode).strip():
        try:
            census_data, _, _ = get_census_data_w_zipcode_fallback(
                str(int(float(zipcode)))
            )
        except Exception as e:
            print(f"[run_batch] census lookup failed for {zipcode}: {e}")


    if force_fresh_llm:
        lead_cache.invalidate(property_name, full_address)


    pipeline = FeaturePipeline(
        property_name=property_name,
        full_address=full_address,
        census_data=census_data,
    )
    features = pipeline.get_features(use_cache=not force_fresh_llm)

    lead_info = get_lead_info(features)

    # Draft email - cached on the same entry as features
    email = lead_cache.get_email(property_name, full_address)
    if email is None:
        em = draft_outreach_email(pipeline.llm_email, row.to_dict(), features, lead_info)

        if em is not None:
            email = em.model_dump(mode="json")
            lead_cache.put_email(property_name, full_address, email)


    return {
        "property_name": property_name,
        "full_address":  full_address,
        "row":           row.to_dict(),
        "features":      features,
        "lead_info":     lead_info,
        "outreach_email": email,
    }


def redraft_email(row: pd.Series) -> Optional[Dict[str, Any]]:
    """Force a fresh email draft using ALREADY-cached features.
    Does NOT re-run Firecrawl or feature LLM calls."""

    property_name    = row["Property Name"]
    property_address = row["Property Address"]
    city             = row["City"]
    state            = row["State"]
    country          = row["Country"]

    full_address = ", ".join([str(property_address), str(city), str(state), str(country)])

    features = lead_cache.get_features(property_name, full_address)

    if features is None:
        print(f"[redraft_email] no cached features for {property_name!r}")
        return None

    lead_info = get_lead_info(features)
    pipeline  = FeaturePipeline(property_name, full_address, census_data=None)

    em = draft_outreach_email(pipeline.llm_email, row.to_dict(), features, lead_info)
    if em is None:
        return None

    email = em.model_dump(mode="json")
    lead_cache.invalidate_email(property_name, full_address)
    lead_cache.put_email(property_name, full_address, email)

    return email



def run_batch(
    csv_path: str = "data/sample_input.csv",
    force_fresh_llm: bool = False,
) -> Iterable[Dict[str, Any]]:

    """Generator — yields results one-at-a-time so a UI can stream progress."""

    if not os.path.exists(csv_path):
        print(f"[run_batch] csv not found: {csv_path}")
        return

    df = pd.read_csv(csv_path)

    for _, row in df.iterrows():
        yield process_row(row, force_fresh_llm=force_fresh_llm)




if __name__ == "__main__":
    for r in run_batch():
        print(r["property_name"], "->", r["lead_info"]["lead_score"])



# # read the CSV file
# if os.path.exists("data/sample_input.csv"):
#     df = pd.read_csv("data/sample_input.csv")

#     for index, row in df.iterrows():
#         name = row['Name']
#         email = row['Email']
#         property_name = row['Property Name']
#         property_address = row['Property Address']
#         city = row['City']
#         state = row['State']
#         zipcode = row['Zipcode']
#         country = row['Country']

#         full_address = ",".join([property_address, city, state, country])
    
#         # get zipcode from property address
#         if pd.isna(zipcode):
#             try:
#                 time.sleep(0.05)
#                 geolocator = Nominatim(user_agent="my_address_app", timeout=5)
#                 location = geolocator.geocode(full_address, addressdetails=True)
#                 zipcode = location.raw.get("address", {}).get("postcode")
#             except Exception as e:
#                 zipcode = None

#         # Get census data
#         if zipcode:
#             census_data, _, _ = get_census_data_w_zipcode_fallback(str(int(zipcode)))
#             print (f'{full_address} - {str(int(zipcode))}')
#             print (census_data)
#             print ('\n')

#             # construct features dictionary
#             features = FeaturePipeline(property_name, full_address, census_data).get_features()

#             # Get lead info
#             lead_info = get_lead_info(features)
# else:
#     print("No CSV file found")
