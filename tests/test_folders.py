import json
import uuid
from pathlib import Path

import create_sql


def _write_chat(tmp_path: Path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_chat_folder_sql_generation(tmp_path: Path):
    chat = {
        "userId": "user-1",
        "title": "Foldered Chat",
        "timestamp": 1000,
        "meta": {"folder_name": " Project One "},
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

    assert user_id == "user-1"
    assert folder_name == "Project One"
    expected_folder_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "user-1:Project One"))
    assert folder_id == expected_folder_id
    assert "folder_id" in sql
    assert expected_folder_id in sql
    assert "project:Project One" in chat_tags
    folder_sql = create_sql.build_folder_insert(
        folder_id=folder_id,
        folder_name=folder_name,
        user_id=user_id,
        created_at=created_at,
        columns=None,
    )
    assert "INSERT INTO \"main\".\"folder\"" in folder_sql
    assert "Project One" in folder_sql
