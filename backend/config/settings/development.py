"""Local development. Security relaxations here are limited to localhost use."""
from .base import *  # noqa: F401,F403

# DEBUG stays False unless DJANGO_DEBUG=True is set explicitly (see base.py).
if not ALLOWED_HOSTS:  # noqa: F405
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Testing on a phone through an HTTPS tunnel (Cloudflare Tunnel, ngrok, localtunnel): accept their host names and their https origins.
# Only here, never in production.py. The names are random each time, so these are wildcards.
TUNNEL_SUFFIXES = (".trycloudflare.com", ".ngrok-free.app", ".ngrok-free.dev", ".loca.lt")
ALLOWED_HOSTS = [*ALLOWED_HOSTS, *TUNNEL_SUFFIXES]  # noqa: F405
CSRF_TRUSTED_ORIGINS = [f"https://*{suffix}" for suffix in TUNNEL_SUFFIXES]

# Uploaded pictures (logo, cover, menu photos) are served by Django here, with or without DEBUG, so they show up on localhost.
SERVE_MEDIA_FILES = True
