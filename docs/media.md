# Pictures: restaurant logo, cover and menu photos

Restaurants upload pictures from their own device. There are no photo links to paste any more.

## What restaurants can do
- **Logo and cover picture:** Dashboard, Settings, "Pictures on your page" (managers and owners). They appear at the top of the restaurant's public page (the logo beside the name, the cover as a banner on the home page).
- **Menu photos:** Dashboard, Menu, add or edit an item, "Photo". Customers see it on the menu and in their cart.
- Older items that still have a photo *link* keep showing it until a photo is uploaded or the picture is removed.

## What the server does with every upload
Nothing the browser sends is trusted (`apps/common/images.py`):
- Only real JPEG, PNG or WebP files are accepted. The file's bytes are opened and checked; the name, extension and declared type are ignored. GIFs, SVGs, PDFs and anything else are refused.
- Up to **3 MB** (`MAX_IMAGE_UPLOAD_BYTES`) and at most 36 million pixels, which stops "decompression bomb" files.
- The picture is rotated as the phone intended, **resized to a fixed frame** (see "Fixed picture sizes" below) and **re-encoded as WebP**. That removes hidden metadata (such as the location in a phone photo) and any payload hidden in the original.
- It is stored under a random name: `restaurants/<restaurant id>/menu|logo|cover/<random>.webp`. Replacing or removing a picture deletes the old file.
- Every change is written to the restaurant's audit log.

## Endpoints (managers and owners of that restaurant)
| Method and path | What it does |
|---|---|
| `POST /restaurants/{slug}/menu/items/{id}/image/` | multipart field `file`: upload an item's photo. Returns the item with `image`. |
| `DELETE /restaurants/{slug}/menu/items/{id}/image/` | remove it |
| `POST /restaurants/{slug}/images/logo/` and `.../images/cover/` | upload the logo or cover. Returns the settings with `logo_url` / `cover_url`. |
| `DELETE` on the same paths | remove it |

Reads: the public restaurant (`GET /restaurants/{slug}/`) now has `logo_url` and `cover_url`. In the public menu, an item's `image_url` is its uploaded photo if it has one, otherwise an older link, otherwise `null`. Staff item payloads also carry `image`. All picture addresses are paths like `/media/restaurants/3/menu/ab12.webp`, relative to your site.

## Setting up
1. `pip install -r requirements/base.txt` (this adds **Pillow**).
2. `python manage.py makemigrations menu restaurants` and `migrate` (adds the `image`, `logo` and `cover_image` columns).
3. Pictures are stored in `MEDIA_ROOT` (default `backend/media`, or set `DJANGO_MEDIA_ROOT`) and addressed under `MEDIA_URL` (`/media/`).
   - In **development** Django serves them (`SERVE_MEDIA_FILES = True` in `development.py`, so it works even with `DEBUG` off), and `frontend/dev_server.py` forwards `/media/` to Django.
   - In **production** serve that folder from your web server (for example an nginx `location /media/` pointing at `MEDIA_ROOT`) or move to object storage. Django doesn't serve media when `DEBUG` is off.
4. **Back up `MEDIA_ROOT`** along with the database.

## Limits to know
- Each restaurant's pictures are public by design (anyone with the address can fetch them), like the menu itself.
- There's no per-restaurant storage cap yet. Each restaurant has one logo, one cover and one photo per item, each at most about a few hundred KB after resizing.

## Fixed picture sizes
Every stored picture has an exact width and height for its kind, so an odd-shaped upload can't disturb the layout:
logo **512 × 512** (the whole logo is kept; empty space is added around it, transparent if the logo has transparency),
cover **588 × 312** and menu photos **1000 × 750** (cropped from the centre to fill the frame). Pictures uploaded before this
change keep their old size until they are uploaded again; the pages crop them to the same frames in the browser.
