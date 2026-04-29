from pydantic import BaseModel, Field, ValidationError
from typing import Any, Dict, List, Optional, Literal


# --------------------------- Buying Trigger Schema ---------------------------

class OwnershipChange(BaseModel):
    bucket: str = "unknown"
    days_ago: Optional[int] = None
    kinds: List[str] = Field(default_factory=list)
    evidence_urls: List[str] = Field(default_factory=list)


class Leaseup(BaseModel):
    value: Optional[bool] = None
    evidence_urls: List[str] = Field(default_factory=list)


class Hiring(BaseModel):
    open_roles: Optional[int] = None
    evidence_urls: List[str] = Field(default_factory=list)


class RecencyAxis(BaseModel):
    bucket: str = "unknown"
    days_ago: Optional[int] = None
    evidence_urls: List[str] = Field(default_factory=list)


class BuyingTriggerPayload(BaseModel):
    ownership_change: OwnershipChange = Field(default_factory=OwnershipChange)
    leaseup: Leaseup = Field(default_factory=Leaseup)
    hiring: Hiring = Field(default_factory=Hiring)
    expansion: RecencyAxis = Field(default_factory=RecencyAxis)
    tech_change: RecencyAxis = Field(default_factory=RecencyAxis)
    evidence_confidence: float = 0.0


# --------------------------- Web Scraping Schema ---------------------------
PropertyType = Literal[
    "multifamily", "student_housing", "affordable_housing",
    "senior_housing", "single_family_home", "commercial_office",
    "hotel", "unknown",
]

class ApartmentsExtraction(BaseModel):
    unit_count: Optional[int] = None
    review_count: Optional[int] = None
    one_star_count: Optional[int] = Field(default=None, alias="1_star_count")
    two_star_count: Optional[int] = Field(default=None, alias="2_star_count")
    manager: Optional[str] = None
    
    model_config = {"populate_by_name": True}


class ZillowExtraction(BaseModel):
    active_listings: Optional[int] = None
    floorplan_count: Optional[int] = None
    manager: Optional[str] = None


class AccountFitLookup(BaseModel):
    manager_portfolio_size: Optional[int] = None
    property_type: Optional[PropertyType] = "unknown"
    detected_pms_vendor: Optional[str] = None


# --------------------------- Outreach Email ---------------------------

class OutreachEmail(BaseModel):
    subject: str
    body: str
    drafted_at: Optional[str] = None