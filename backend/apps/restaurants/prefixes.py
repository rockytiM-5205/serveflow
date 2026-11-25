"""Suggesting and assigning each restaurant's own order-ID prefix (the PRM in PRM-8K29P)."""
import re
import secrets

# No I, L or O (they look like 1 and 0), matching the order reference alphabet.
_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"
_FILLER = "23456789" + _LETTERS


def suggest_prefix(name):
    """Three letters taken from the name: the words' initials first, then more letters from the first word."""
    words = re.findall(r"[A-Za-z]+", name or "")
    picked = [w[0].upper() for w in words][:3]
    if words:
        for letter in words[0][1:].upper():
            if len(picked) >= 3:
                break
            picked.append(letter)
    base = "".join(picked)
    while len(base) < 3:
        base += secrets.choice(_LETTERS)
    return base[:3]


def unique_prefix(name, is_taken):
    """The first free prefix: the suggestion, then it with its last character changed, then a longer one."""
    base = suggest_prefix(name)
    if not is_taken(base):
        return base
    for _ in range(40):
        candidate = base[:2] + secrets.choice(_FILLER)
        if not is_taken(candidate):
            return candidate
    for _ in range(200):
        candidate = base[:2] + "".join(secrets.choice(_FILLER) for _ in range(3))
        if not is_taken(candidate):
            return candidate
    raise RuntimeError("Could not find a free order prefix.")
