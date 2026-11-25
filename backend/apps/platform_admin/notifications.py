"""Raising and reading platform-owner notifications. Never raises into the code that calls it: a notification is a courtesy."""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PlatformNotification

logger = logging.getLogger(__name__)


def notify(kind, title, detail="", link="", restaurant=None, dedupe_key=None):
    """Create a notification once per `dedupe_key`. Returns it, or None when it already existed or couldn't be made."""
    try:
        with transaction.atomic():  # a savepoint: a failure here must not poison the caller's transaction
            if dedupe_key:
                note, created = PlatformNotification.objects.get_or_create(
                    dedupe_key=dedupe_key, defaults={"kind": kind, "title": title[:120], "detail": detail[:255], "link": link[:120], "restaurant": restaurant})
                return note if created else None
            return PlatformNotification.objects.create(kind=kind, title=title[:120], detail=detail[:255], link=link[:120], restaurant=restaurant)
    except IntegrityError:
        return None  # another worker raised the same event first
    except Exception:  # noqa: BLE001 - never break the action that raised it
        logger.exception("Couldn't create a notification")
        return None


def serialize(note):
    return {"id": note.pk, "kind": note.kind, "title": note.title, "detail": note.detail, "link": note.link, "created_at": note.created_at, "read": note.read_at is not None}


def summary(limit=10):
    return {
        "unread": PlatformNotification.objects.filter(read_at__isnull=True).count(),
        "results": [serialize(n) for n in PlatformNotification.objects.order_by("-created_at", "-id")[:limit]],
    }


def mark_read(ids=None):
    """Mark the given notifications (or all of them) read. Returns how many changed."""
    notes = PlatformNotification.objects.filter(read_at__isnull=True)
    if ids is not None:
        notes = notes.filter(pk__in=ids)
    return notes.update(read_at=timezone.now())
