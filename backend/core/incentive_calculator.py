"""
JSY / JSSK Incentive Calculator
=================================
ASHA workers are paid per verified event, not salary.
Disputed calculations are the #1 source of ASHA attrition.
This module auto-calculates earned incentives from logged visit data.

Source: MOHFW "Janani Suraksha Yojana — Operational Guidelines", 2015
        MOHFW "JSSK Operational Framework", 2011
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IncentiveType(str, Enum):
    # JSY — Janani Suraksha Yojana
    JSY_INSTITUTIONAL_DELIVERY_RURAL  = "jsy_delivery_rural"   # ₹1400
    JSY_INSTITUTIONAL_DELIVERY_URBAN  = "jsy_delivery_urban"   # ₹1000
    JSY_HOME_DELIVERY                 = "jsy_home_delivery"    # ₹500
    # ANC registration + completion
    ANC_REGISTRATION                  = "anc_registration"     # ₹300
    ANC_4TH_CONTACT                   = "anc_4th_contact"      # ₹300
    # Immunisation (VHND-based)
    IMMUNISATION_BCG                  = "imm_bcg"              # ₹150
    IMMUNISATION_PENTA_DOSE           = "imm_penta"            # ₹150
    IMMUNISATION_MEASLES              = "imm_measles"          # ₹150
    # Referral escort
    REFERRAL_ESCORT                   = "referral_escort"      # ₹250
    # VHND attendance
    VHND_SESSION                      = "vhnd_session"         # ₹200/session
    # NRC admission support
    NRC_ADMISSION                     = "nrc_admission"        # ₹500


# Incentive amounts in INR (as per MOHFW operational guidelines)
INCENTIVE_AMOUNTS: dict[IncentiveType, int] = {
    IncentiveType.JSY_INSTITUTIONAL_DELIVERY_RURAL: 1400,
    IncentiveType.JSY_INSTITUTIONAL_DELIVERY_URBAN: 1000,
    IncentiveType.JSY_HOME_DELIVERY:                 500,
    IncentiveType.ANC_REGISTRATION:                  300,
    IncentiveType.ANC_4TH_CONTACT:                   300,
    IncentiveType.IMMUNISATION_BCG:                  150,
    IncentiveType.IMMUNISATION_PENTA_DOSE:            150,
    IncentiveType.IMMUNISATION_MEASLES:               150,
    IncentiveType.REFERRAL_ESCORT:                    250,
    IncentiveType.VHND_SESSION:                       200,
    IncentiveType.NRC_ADMISSION:                      500,
}


@dataclass
class IncentiveEvent:
    type: IncentiveType
    amount: int
    patient_id: str
    patient_name: str
    event_date: str
    verified: bool = False
    notes: str = ""


def calculate_incentives_from_visit(
    visit_type: str,
    observations: dict,
    patient: dict,
    is_rural: bool = True,
) -> list[IncentiveEvent]:
    """
    Derive earned incentive events from a logged visit record.
    Returns list of IncentiveEvent objects for persistence.
    """
    events: list[IncentiveEvent] = []
    pname = patient.get("name", "Unknown")
    pid = patient.get("id", "")
    vdate = observations.get("visit_date", "")

    # --- ANC registration ---
    if visit_type == "anc_registration":
        events.append(IncentiveEvent(
            type=IncentiveType.ANC_REGISTRATION,
            amount=INCENTIVE_AMOUNTS[IncentiveType.ANC_REGISTRATION],
            patient_id=pid, patient_name=pname, event_date=vdate,
            notes="ANC registration completed"
        ))

    # --- 4th ANC contact ---
    if visit_type == "anc" and observations.get("anc_contact_number") == 4:
        events.append(IncentiveEvent(
            type=IncentiveType.ANC_4TH_CONTACT,
            amount=INCENTIVE_AMOUNTS[IncentiveType.ANC_4TH_CONTACT],
            patient_id=pid, patient_name=pname, event_date=vdate,
        ))

    # --- Institutional delivery ---
    if visit_type == "delivery" and observations.get("delivery_place") == "institution":
        itype = (IncentiveType.JSY_INSTITUTIONAL_DELIVERY_RURAL if is_rural
                 else IncentiveType.JSY_INSTITUTIONAL_DELIVERY_URBAN)
        events.append(IncentiveEvent(
            type=itype,
            amount=INCENTIVE_AMOUNTS[itype],
            patient_id=pid, patient_name=pname, event_date=vdate,
        ))

    # --- Home delivery ---
    if visit_type == "delivery" and observations.get("delivery_place") == "home":
        events.append(IncentiveEvent(
            type=IncentiveType.JSY_HOME_DELIVERY,
            amount=INCENTIVE_AMOUNTS[IncentiveType.JSY_HOME_DELIVERY],
            patient_id=pid, patient_name=pname, event_date=vdate,
        ))

    # --- Immunisations given ---
    vaccines_given: list[str] = observations.get("vaccines_given", [])
    vaccine_map = {
        "bcg": IncentiveType.IMMUNISATION_BCG,
        "penta1": IncentiveType.IMMUNISATION_PENTA_DOSE,
        "penta2": IncentiveType.IMMUNISATION_PENTA_DOSE,
        "penta3": IncentiveType.IMMUNISATION_PENTA_DOSE,
        "measles": IncentiveType.IMMUNISATION_MEASLES,
    }
    seen_penta = False
    for vaccine in vaccines_given:
        itype = vaccine_map.get(vaccine.lower())
        if itype:
            if itype == IncentiveType.IMMUNISATION_PENTA_DOSE and seen_penta:
                continue  # one incentive per session, not per dose
            if itype == IncentiveType.IMMUNISATION_PENTA_DOSE:
                seen_penta = True
            events.append(IncentiveEvent(
                type=itype,
                amount=INCENTIVE_AMOUNTS[itype],
                patient_id=pid, patient_name=pname, event_date=vdate,
                notes=f"Vaccine: {vaccine}"
            ))

    # --- Referral escort ---
    if observations.get("referral_escorted"):
        events.append(IncentiveEvent(
            type=IncentiveType.REFERRAL_ESCORT,
            amount=INCENTIVE_AMOUNTS[IncentiveType.REFERRAL_ESCORT],
            patient_id=pid, patient_name=pname, event_date=vdate,
        ))

    # --- NRC admission ---
    if observations.get("nrc_admitted"):
        events.append(IncentiveEvent(
            type=IncentiveType.NRC_ADMISSION,
            amount=INCENTIVE_AMOUNTS[IncentiveType.NRC_ADMISSION],
            patient_id=pid, patient_name=pname, event_date=vdate,
        ))

    return events


def summarise_incentives(events: list[dict]) -> dict:
    """Aggregate earned/pending/verified amounts for ASHA dashboard."""
    total_earned = sum(e["amount"] for e in events)
    total_verified = sum(e["amount"] for e in events if e.get("verified"))
    pending = total_earned - total_verified

    by_type: dict[str, dict] = {}
    for e in events:
        t = e["type"]
        if t not in by_type:
            by_type[t] = {"count": 0, "total": 0}
        by_type[t]["count"] += 1
        by_type[t]["total"] += e["amount"]

    return {
        "total_earned": total_earned,
        "total_verified": total_verified,
        "pending_payment": pending,
        "breakdown": by_type,
        "event_count": len(events),
    }
