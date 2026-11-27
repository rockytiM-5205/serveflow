import hashlib
import re

from apps.common.throttles import GlobalThrottle, SimpleRateThrottle


class OrderPhoneThrottle(SimpleRateThrottle):
    """Caps orders per phone number per restaurant, whatever IP they come from."""

    scope = "order_phone"

    def get_cache_key(self, request, view):
        data = request.data
        phone = re.sub(r"\D", "", str(data.get("customer_phone", ""))) if hasattr(data, "get") else ""
        if not phone:
            return None
        ident = hashlib.sha256(f"{view.kwargs.get('slug')}:{phone}".encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OrderRestaurantThrottle(SimpleRateThrottle):
    """Caps ALL new orders at one restaurant together (every caller, every address), so one restaurant's kitchen screen can't be
    flooded even by someone who rotates addresses and phone numbers."""

    scope = "order_restaurant"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": str(view.kwargs.get("slug", ""))}
