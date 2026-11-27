# Order alerts fix + Cloudinary check
Copy these INTO the existing folders (merge, do not replace whole folders). No migration.
New: backend/apps/restaurants/management/commands/check_cloudinary.py
Edited: backend/apps/restaurants/push.py (urgent delivery), frontend/restaurant-dashboard/js/push-client.js, shell.js, settings.js,
        frontend/shared/js/sw-core.js (sticky alerts), frontend/tests/pwa.test.mjs (+1 test)
After deploying, on every phone: Settings > Order alerts > turn alerts off, then on again.
