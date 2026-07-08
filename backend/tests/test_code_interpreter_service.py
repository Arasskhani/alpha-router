"""Tests for sandboxed code interpreter helpers."""

import pytest

from app.services.code_interpreter_service import (
    code_interpreter_system_message,
    extract_last_python_block,
    format_code_output_for_chat,
    validate_python_code,
    workspace_files_from_messages,
)


def test_extract_last_python_block():
    text = "Try this:\n```python\nprint(1)\n```\nand\n```py\nprint(2)\n```"
    assert extract_last_python_block(text) == "print(2)"


def test_validate_python_code_blocks_os_import():
    with pytest.raises(ValueError, match="Import not allowed"):
        validate_python_code("import os\nprint(os.getcwd())")


def test_workspace_files_from_attachment_sections():
    messages = [
        {
            "role": "user",
            "content": "Analyze\n\n--- sales.csv ---\nname,value\na,1\nb,2",
        }
    ]
    files = workspace_files_from_messages(messages)
    assert files["sales.csv"].startswith("name,value")


def test_code_interpreter_system_english_comments_and_ltr():
    msg = code_interpreter_system_message()
    assert "English-only comments" in msg
    assert "Persian/Farsi comments" in msg
    assert "Keep all code LTR" in msg


def test_format_code_output_uses_text_fence():
    out = format_code_output_for_chat("hello\nworld")
    assert "```text\nhello\nworld\n```" in out


def test_workspace_files_from_attach_json():
    payload = (
        '__NITRO_ATTACH_JSON__:{"userText":"go","attachments":[{"name":"data.csv","kind":"document",'
        '"mime_type":"text/csv","url":"","text":"x,y\\n1,2"}]}'
    )
    files = workspace_files_from_messages([{"role": "user", "content": payload}])
    assert "data.csv" in files
