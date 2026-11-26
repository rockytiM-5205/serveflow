# Deployment: Render + Vercel + Neon + Cloudinary
No migration. Copy over your project keeping paths, then follow docs/deploy.md. This replaces the previous deploy zip.

New: `render.yaml`, `docs/deploy.md`, `frontend/vercel.json`, `frontend/.vercelignore`, `backend/apps/common/storage.py`
Edited: `backend/config/settings/base.py`, `backend/config/settings/production.py`, `backend/config/urls.py`, `backend/requirements/base.txt`,
`backend/apps/restaurants/manifest.py`, `backend/tests/test_settings.py`, `backend/tests/test_images.py`, `.env.example`

Before deploying: edit `frontend/vercel.json` and replace YOUR-SERVICE.onrender.com (2 places).
Then run: pip install -r backend/requirements/development.txt && pytest
