// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { MAX_IMAGE_BYTES, checkImageFile } from "../shared/js/image-picker.js";
import { isImageSource } from "../shared/js/validators.js";

test("checkImageFile accepts real picture types within the size limit", () => {
  assert.equal(checkImageFile({ type: "image/jpeg", size: 1000 }), null);
  assert.equal(checkImageFile({ type: "image/png", size: MAX_IMAGE_BYTES }), null);
  assert.equal(checkImageFile({ type: "image/webp", size: 5 }), null);
});

test("checkImageFile refuses other types, too-big files and no file", () => {
  assert.match(checkImageFile({ type: "image/gif", size: 10 }), /JPEG, PNG or WebP/);
  assert.match(checkImageFile({ type: "image/svg+xml", size: 10 }), /JPEG, PNG or WebP/);
  assert.match(checkImageFile({ type: "application/pdf", size: 10 }), /JPEG, PNG or WebP/);
  assert.match(checkImageFile({ type: "image/png", size: MAX_IMAGE_BYTES + 1 }), /too large/);
  assert.match(checkImageFile(null), /Choose a picture/);
});

test("pages only show pictures from /media/ or https links", () => {
  assert.equal(isImageSource("/media/restaurants/3/menu/abc.webp"), true);
  assert.equal(isImageSource("https://cdn.example.com/rice.jpg"), true);
  assert.equal(isImageSource("/media/../etc/passwd"), false);
  assert.equal(isImageSource("http://insecure.example.com/a.jpg"), false);
  assert.equal(isImageSource("javascript:alert(1)"), false);
  assert.equal(isImageSource("//evil.example.com/a.jpg"), false);
  assert.equal(isImageSource(null), false);
});
