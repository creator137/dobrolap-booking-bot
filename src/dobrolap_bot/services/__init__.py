from dobrolap_bot.services.booking import BookingService, InvalidTransitionError, can_transition, transition
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService
__all__ = [
    "BookingService",
    "InvalidTransitionError",
    "PlacementService",
    "PricingService",
    "can_transition",
    "format_client_status",
    "format_owner_summary",
    "transition",
]


def __getattr__(name: str):
    if name in {"format_client_status", "format_owner_summary"}:
        from dobrolap_bot.services.summary import format_client_status, format_owner_summary

        return {
            "format_client_status": format_client_status,
            "format_owner_summary": format_owner_summary,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
