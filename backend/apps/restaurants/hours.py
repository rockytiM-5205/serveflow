"""Opening hours and availability, always judged in the restaurant's own timezone."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def local_now(restaurant, now=None):
    return (now or timezone.now()).astimezone(ZoneInfo(restaurant.timezone))


def periods_of(restaurant):
    """All periods, using the prefetch cache when the caller loaded it."""
    return list(restaurant.opening_periods.all())


def has_hours(restaurant):
    return bool(periods_of(restaurant))


def is_open_now(restaurant, now=None):
    """True or False when hours are published, None when the restaurant hasn't published any."""
    periods = periods_of(restaurant)
    if not periods:
        return None
    local = local_now(restaurant, now)
    current = local.time().replace(second=0, microsecond=0)
    return any(p.weekday == local.weekday() and p.opens <= current < p.closes for p in periods)


def availability(restaurant, now=None):
    """OPEN, CLOSED (outside published hours) or PAUSED (the restaurant isn't taking orders right now)."""
    if not restaurant.accepting_orders:
        return "PAUSED"
    return "CLOSED" if is_open_now(restaurant, now) is False else "OPEN"


def hours_table(restaurant):
    """Seven rows, Monday first, each with its periods as HH:MM strings."""
    by_day = {i: [] for i in range(7)}
    for p in periods_of(restaurant):
        by_day[p.weekday].append({"opens": p.opens.strftime("%H:%M"), "closes": p.closes.strftime("%H:%M")})
    return [{"weekday": i, "day": WEEKDAYS[i], "periods": by_day[i]} for i in range(7)]


def parse_time(value):
    return datetime.strptime(value, "%H:%M").time()


def validate_periods(rows):
    """rows: [{"weekday", "opens", "closes"}] as strings. Returns clean tuples or raises ValueError with a readable message."""
    clean = []
    for row in rows:
        try:
            weekday = int(row["weekday"])
            opens, closes = parse_time(str(row["opens"])), parse_time(str(row["closes"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each period needs a weekday (0-6) and opening and closing times like 09:00.") from None
        if not 0 <= weekday <= 6:
            raise ValueError("The weekday must be 0 (Monday) to 6 (Sunday).")
        if closes <= opens:
            raise ValueError(f"{WEEKDAYS[weekday]}: closing time must be after opening time. For a late night, split it at midnight.")
        clean.append((weekday, opens, closes))
    clean.sort()
    for earlier, later in zip(clean, clean[1:]):
        if earlier[0] == later[0] and later[1] < earlier[2]:
            raise ValueError(f"{WEEKDAYS[earlier[0]]}: opening periods overlap.")
    if len(clean) > 28:
        raise ValueError("That is too many opening periods.")
    return clean


# ------------------------------------------------------------------ pickup times
def pickup_lead_minutes():
    return getattr(settings, "PICKUP_MIN_LEAD_MINUTES", 30)


def _slack():
    return timedelta(minutes=getattr(settings, "PICKUP_LEAD_SLACK_MINUTES", 5))


def _inside_hours(restaurant, when_utc):
    """Is `when_utc` inside a published opening period? True when the restaurant hasn't published any hours."""
    periods = periods_of(restaurant)
    if not periods:
        return True
    local = when_utc.astimezone(ZoneInfo(restaurant.timezone))
    current = local.time().replace(second=0, microsecond=0)
    return any(p.weekday == local.weekday() and p.opens <= current < p.closes for p in periods)


def pickup_problem(restaurant, when, now=None):
    """Why `when` can't be a pickup time, or None if it can. At least 30 minutes ahead (a few minutes of slack so a customer
    who is still filling in the form isn't punished), within 48 hours, and while the restaurant is open."""
    now = now or timezone.now()
    if when < now + timedelta(minutes=pickup_lead_minutes()) - _slack():
        return f"Pickup is at least {pickup_lead_minutes()} minutes from now. Please choose a later time."
    if when > now + timedelta(hours=getattr(settings, "PICKUP_MAX_HOURS", 48)):
        return "That is too far ahead. Please choose a time within the next two days."
    if not _inside_hours(restaurant, when):
        return "The restaurant is closed at that time. Please choose a time when it is open."
    return None


def pickup_slots(restaurant, now=None):
    """Times a customer can choose: every 15 minutes from 30 minutes ahead, while the restaurant is open. With no published hours
    only the next 12 hours are offered, because we can't tell when the restaurant closes."""
    now = now or timezone.now()
    step = timedelta(minutes=getattr(settings, "PICKUP_SLOT_MINUTES", 15))
    first = now + timedelta(minutes=pickup_lead_minutes())
    first = first.replace(second=0, microsecond=0)
    first += (step - timedelta(minutes=first.minute % (step.seconds // 60))) % step  # round up to the 15-minute grid
    published = has_hours(restaurant)
    horizon = now + timedelta(hours=getattr(settings, "PICKUP_MAX_HOURS", 48) if published else 12)
    zone = ZoneInfo(restaurant.timezone)
    today = now.astimezone(zone).date()
    slots, when = [], first
    while when <= horizon:
        if _inside_hours(restaurant, when):
            local = when.astimezone(zone)
            day = {0: "Today", 1: "Tomorrow"}.get((local.date() - today).days, local.strftime("%a %d %b"))
            slots.append({"at": when.isoformat(), "date": local.date().isoformat(), "day": day, "time": local.strftime("%H:%M")})
        when += step
    return slots
