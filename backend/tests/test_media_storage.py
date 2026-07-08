"""Media object keys and normalized content hashing."""

import io

from app.api.images import _collect_openrouter_images
from app.services.object_storage_service import media_object_key
from app.services.storage_service import media_content_hash


def test_media_object_key_uses_username_slug():
    key = media_object_key("jdoe", "abc123", ".png")
    assert key == "cdn/u/jdoe/abc123.png"


def test_media_content_hash_stable_for_identical_bytes():
    from PIL import Image

    img = Image.new("RGB", (8, 8), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    _, _, h1 = media_content_hash(raw, "image/png", "image")
    _, _, h2 = media_content_hash(raw, "image/png", "image")
    assert h1 == h2


def test_collect_openrouter_skips_top_level_data_when_choices_have_images():
    data = {
        "choices": [
            {
                "message": {
                    "images": [{"b64_json": "YmFy"}],
                }
            }
        ],
        "data": [{"url": "https://cdn.example.com/dup.png"}],
    }
    items = _collect_openrouter_images(data)
    assert len(items) == 1
    assert items[0] == {"b64_json": "YmFy"}
