__all__ = ["BookingForm", "OwnerForm", "owner_router", "router"]


def __getattr__(name: str):
    if name == "router":
        from dobrolap_bot.bot.handlers import router

        return router
    if name == "owner_router":
        from dobrolap_bot.bot.owner import router as owner_router

        return owner_router
    if name in {"BookingForm", "OwnerForm"}:
        from dobrolap_bot.bot.states import BookingForm, OwnerForm

        return {"BookingForm": BookingForm, "OwnerForm": OwnerForm}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
