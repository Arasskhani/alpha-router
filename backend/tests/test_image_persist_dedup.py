"""Ensure image payload collectors do not duplicate url + b64_json for one image."""

from app.api.images import (
    _collect_openrouter_images,
    _collect_standard_image_payload,
    _coalesce_image_item,
    _dedupe_image_items,
)


def test_coalesce_prefers_b64_over_url():
    item = _coalesce_image_item(url="https://example.com/a.png", b64="abc123")
    assert item == {"b64_json": "abc123"}


def test_collect_standard_payload_one_item_when_both_fields_present():
    data = {
        "data": [
            {
                "url": "https://cdn.example.com/image.png",
                "b64_json": "Zm9v",
            }
        ]
    }
    items = _collect_standard_image_payload(data)
    assert len(items) == 1
    assert items[0] == {"b64_json": "Zm9v"}


def test_collect_openrouter_images_coalesces_per_image_object():
    data = {
        "choices": [
            {
                "message": {
                    "images": [
                        {
                            "image_url": {"url": "https://cdn.example.com/out.png"},
                            "b64_json": "YmFy",
                        }
                    ]
                }
            }
        ]
    }
    items = _collect_openrouter_images(data)
    assert len(items) == 1
    assert items[0] == {"b64_json": "YmFy"}


def test_dedupe_image_items_by_payload_key():
    items = [
        {"url": "https://cdn.example.com/same.png"},
        {"url": "https://cdn.example.com/same.png"},
        {"b64_json": "unique"},
    ]
    assert _dedupe_image_items(items) == [
        {"url": "https://cdn.example.com/same.png"},
        {"b64_json": "unique"},
    ]


def test_collect_openrouter_skips_message_level_when_images_array_present():
    data = {
        "choices": [
            {
                "message": {
                    "images": [
                        {
                            "image_url": {"url": "https://cdn.example.com/out.png"},
                            "b64_json": "YmFy",
                        }
                    ],
                    "image_url": {"url": "https://cdn.example.com/dup.png"},
                    "b64_json": "other",
                    "content": "![img](https://cdn.example.com/markdown.png)",
                }
            }
        ]
    }
    items = _collect_openrouter_images(data)
    assert len(items) == 1
    assert items[0] == {"b64_json": "YmFy"}


def test_collect_openrouter_images_accepts_camelcase_image_url():
    data = {
        "choices": [
            {
                "message": {
                    "content": "Here is your image.",
                    "images": [
                        {
                            "type": "image_url",
                            "imageUrl": {"url": "data:image/png;base64,Zm9vYmFy"},
                        }
                    ],
                }
            }
        ]
    }
    items = _collect_openrouter_images(data)
    assert len(items) == 1
    assert items[0]["url"].startswith("data:image/png;base64,")


def test_collect_openrouter_falls_through_when_images_unparseable():
    data = {
        "choices": [
            {
                "message": {
                    "images": [{"type": "image_url", "image_url": {}}],
                    "content": "![img](https://cdn.example.com/from-markdown.png)",
                }
            }
        ]
    }
    items = _collect_openrouter_images(data)
    assert items == [{"url": "https://cdn.example.com/from-markdown.png"}]
