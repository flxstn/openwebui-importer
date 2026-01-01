import json
from pathlib import Path

import create_sql


def _write_chat(tmp_path: Path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_sql_output_has_no_on_conflict(tmp_path: Path) -> None:
    chat = {
        "userId": "user-1",
        "title": "No Conflict Chat",
        "timestamp": 1000,
        "meta": {"folder_name": "Project One"},
    }
    filename = "foldered_00000000-0000-0000-0000-000000000001.json"
    path = _write_chat(tmp_path, filename, chat)

    sql, user_id, folder_name, folder_id, chat_tags, created_at = create_sql.json_to_sql(
        path,
        ["imported-chatgpt"],
        "project:",
        {},
        None,
    )
    folder_sql = create_sql.build_folder_insert(
        folder_id=folder_id,
        folder_name=folder_name,
        user_id=user_id,
        created_at=created_at,
        columns=None,
    )
    tag_sql = create_sql.tag_upserts(user_id, sorted(chat_tags), None)

    combined = "\n".join(tag_sql + [folder_sql, sql])
    assert "ON CONFLICT" not in combined
