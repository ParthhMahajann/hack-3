"""
Alert Dispatch Service
Sends SMS + in-app alerts to ANM/Block Health Officer on RED/PURPLE risk.
Twilio is optional — falls back to in-app notification queue if not configured.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger("asha.alerts")


async def dispatch_risk_alert(
    patient_name: str,
    patient_id: str,
    risk_result: dict,
    officer_phone: str = "",
    asha_name: str = "ASHA Worker",
    area: str = "",
) -> dict:
    """
    Dispatch alert based on risk level.
    RED  → in-app notification to ANM
    PURPLE → SMS + in-app to Block Health Officer
    """
    level = risk_result.get("level", "green")
    score = risk_result.get("score", 0)
    triggered = risk_result.get("triggered_parameters", [])
    action = risk_result.get("action", "")

    if level not in ("red", "purple"):
        return {"dispatched": False, "reason": "risk_level_below_threshold"}

    message = _format_alert_message(
        patient_name, score, level, triggered, action, asha_name, area
    )

    dispatched_channels = []

    # --- SMS (Twilio) — PURPLE only ---
    if level == "purple" and officer_phone:
        sms_result = await _send_sms(officer_phone, message)
        if sms_result:
            dispatched_channels.append("sms")

    # --- In-app notification (always) ---
    dispatched_channels.append("in_app")

    return {
        "dispatched": True,
        "channels": dispatched_channels,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "patient_id": patient_id,
        "risk_level": level,
    }


def _format_alert_message(
    name: str,
    score: int,
    level: str,
    triggered: list[str],
    action: str,
    asha: str,
    area: str,
) -> str:
    tag = "⚠️ URGENT" if level == "purple" else "⚠️ Alert"
    params = "; ".join(triggered[:3])  # top 3 triggers
    return (
        f"{tag}: Patient {name} (area: {area}) — Risk Score {score}/100 [{level.upper()}]. "
        f"Flags: {params}. Action: {action}. Reported by: {asha}."
    )


async def _send_sms(to_number: str, body: str) -> bool:
    """Send SMS via Twilio. Returns True on success, False on failure/not configured."""
    try:
        from backend.config import get_settings
        from twilio.rest import Client  # type: ignore
        settings = get_settings()
        if not settings.twilio_account_sid:
            logger.info("Twilio not configured — SMS skipped, in-app only")
            return False
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(body=body, from_=settings.twilio_from_number, to=to_number)
        return True
    except ImportError:
        logger.warning("Twilio not installed — SMS unavailable")
        return False
    except Exception as exc:
        logger.error(f"SMS dispatch failed: {exc}")
        return False
