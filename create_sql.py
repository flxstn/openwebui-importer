#!/usr/bin/env python3
"""Generate SQL insert statements from open-webui chat JSON files."""
import argparse
import json
import os
import sqlite3
import uuid
import re


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def escape_sql_string(value: str) -> str:
    return value.replace("'", "''")


def build_meta(tags: list[str]) -> str:
    meta = json.dumps({"tags": tags}, ensure_ascii=True)
    return escape_sql_string(meta)


def slugify(value: str) -> str:
    """Return a slug suitable for use as an identifier."""
    value = value.lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def tag_upserts(user_id: str, meta_tags: list[str]) -> list[str]:
    """Return SQL statements to ensure tags exist for the user."""
    base_tags = [
        ("imported-grok", "imported-grok"),
        ("imported-chatgpt", "imported-chatgpt"),
        ("imported-claude", "imported-claude"),
    ]
    for t in meta_tags:
        slug = slugify(t)
        base_tags.append((slug, t))

    unique: dict[str, str] = {}
    for tag_id, name in base_tags:
        unique[tag_id] = name

    stmts = []
    for tag_id, name in unique.items():
        stmts.append(
            'INSERT INTO "main"."tag" ("id","name","user_id","meta") '
            f"VALUES ('{tag_id}','{name}','{user_id}','null') "
            'ON CONFLICT("id","user_id") DO UPDATE SET "name"=excluded."name";'
        )
    return stmts

def sanitize_folder_name(name: str | None) -> str:
    if not isinstance(name, str):
        return ""
    cleaned = re.sub(r"[\ue000-\uf8ff]", "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80]


def load_folder_manifest(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = load_json(path)
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            cleaned = sanitize_folder_name(str(value))
            if cleaned:
                result[str(key)] = cleaned
        return result
    if isinstance(data, list):
        result: dict[str, str] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            conv_id = entry.get("conversation_id") or entry.get("id")
            name = entry.get("folder_name") or entry.get("project_name")
            if conv_id and name:
                cleaned = sanitize_folder_name(str(name))
                if cleaned:
                    result[str(conv_id)] = cleaned
        return result
    raise ValueError("Folder manifest must be a JSON object or list")


def load_table_columns(db_path: str | None, table: str) -> set[str] | None:
    if not db_path:
        return None
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def normalize_chat_payload(data: object) -> dict:
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict) and isinstance(data.get("chat"), dict):
        chat = data["chat"]
        return {
            "chat": chat,
            "user_id": data.get("user_id") or data.get("userId") or chat.get("userId"),
            "title": data.get("title") or chat.get("title") or "",
            "meta": data.get("meta") or chat.get("meta") or {},
        }
    if isinstance(data, dict):
        return {
            "chat": data,
            "user_id": data.get("userId"),
            "title": data.get("title") or "",
            "meta": data.get("meta") or {},
        }
    return {"chat": {}, "user_id": None, "title": "", "meta": {}}


def extract_folder_name(
    payload: dict,
    folder_map: dict[str, str],
    record_id: str,
) -> str:
    mapped = folder_map.get(record_id)
    if mapped:
        return mapped
    meta = payload.get("meta")
    if isinstance(meta, dict):
        candidate = meta.get("folder_name") or meta.get("folderName")
        if candidate:
            return sanitize_folder_name(str(candidate))
    candidate = payload.get("chat", {}).get("folder_name") if isinstance(payload.get("chat"), dict) else None
    if candidate:
        return sanitize_folder_name(str(candidate))
    return ""


def build_folder_id(user_id: str, folder_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{user_id}:{folder_name}"))


def build_folder_insert(
    folder_id: str,
    folder_name: str,
    user_id: str,
    created_at: int,
    columns: set[str] | None,
) -> str:
    values = {
        "id": f"'{folder_id}'",
        "name": f"'{escape_sql_string(folder_name)}'",
        "user_id": f"'{user_id}'",
        "created_at": str(created_at),
        "updated_at": str(created_at),
        "meta": "'null'",
        "parent_id": "NULL",
    }
    if columns is None:
        include = ["id", "name", "user_id", "created_at", "updated_at", "meta", "parent_id"]
    else:
        include = [col for col in values.keys() if col in columns]
    cols = ",".join(f"\"{col}\"" for col in include)
    vals = ",".join(values[col] for col in include)
    update_parts = []
    if "name" in include:
        update_parts.append("\"name\"=excluded.\"name\"")
    if "updated_at" in include:
        update_parts.append("\"updated_at\"=excluded.\"updated_at\"")
    update_clause = " DO UPDATE SET " + ",".join(update_parts) if update_parts else " DO NOTHING"
    return (
        "INSERT INTO \"main\".\"folder\" "
        f"({cols}) VALUES ({vals}) ON CONFLICT(\"id\"){update_clause};"
    )


def build_chat_insert(
    record_id: str,
    user_id: str,
    title: str,
    created_at: int,
    chat_json: str,
    meta: str,
    folder_id: str | None,
    columns: set[str] | None,
) -> str:
    values = {
        "id": f"'{record_id}'",
        "user_id": f"'{user_id}'",
        "title": f"'{title}'",
        "share_id": "NULL",
        "archived": "0",
        "created_at": str(created_at),
        "updated_at": str(created_at),
        "chat": f"'{chat_json}'",
        "pinned": "0",
        "meta": f"'{meta}'",
        "folder_id": f"'{folder_id}'" if folder_id else "NULL",
    }
    if columns is None:
        include = list(values.keys())
    else:
        include = [col for col in values.keys() if col in columns]
    cols = ",".join(f"\"{col}\"" for col in include)
    vals = ",".join(values[col] for col in include)
    return (
        f"DELETE FROM \"main\".\"chat\" WHERE \"id\" = '{record_id}';\n"
        "INSERT INTO \"main\".\"chat\" "
        f"({cols})\n"
        f"VALUES ({vals});"
    )


def json_to_sql(
    path: str,
    tags: list[str],
    folder_tag_prefix: str,
    folder_map: dict[str, str],
    chat_columns: set[str] | None,
) -> tuple[str, str, str, str | None, list[str], int]:
    data = load_json(path)
    payload = normalize_chat_payload(data)
    chat = payload["chat"]
    if not isinstance(chat, dict) or not chat:
        raise ValueError(f"Chat payload missing in {path}")
    chat_json = json.dumps(chat, ensure_ascii=True)
    chat_json = escape_sql_string(chat_json)

    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError(f"userId missing in {path}")
    title = escape_sql_string(payload.get("title", ""))
    timestamp_ms = chat.get("timestamp", 0)
    created_at = int(int(timestamp_ms) / 1000)

    base = os.path.splitext(os.path.basename(path))[0]
    possible_id = base.split("_")[-1]
    try:
        uuid.UUID(possible_id)
        record_id = possible_id
    except ValueError:
        record_id = str(uuid.uuid4())

    folder_name = extract_folder_name(payload, folder_map, record_id)
    folder_id = build_folder_id(user_id, folder_name) if folder_name else None
    chat_tags = list(dict.fromkeys(tags))
    if folder_name and folder_tag_prefix:
        folder_tag = f"{folder_tag_prefix}{folder_name}"
        if folder_tag not in chat_tags:
            chat_tags.append(folder_tag)

    meta = build_meta(chat_tags)

    sql = build_chat_insert(
        record_id=record_id,
        user_id=user_id,
        title=title,
        created_at=created_at,
        chat_json=chat_json,
        meta=meta,
        folder_id=folder_id,
        columns=chat_columns,
    )
    return sql, user_id, folder_name, folder_id, chat_tags, created_at


def gather_files(paths: list[str]) -> list[str]:
    result = []
    for p in paths:
        if os.path.isdir(p):
            for name in os.listdir(p):
                if name.endswith('.json'):
                    result.append(os.path.join(p, name))
        else:
            result.append(p)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SQL inserts for open-webui chats")
    parser.add_argument("files", nargs="+", help="Chat JSON files or directories")
    parser.add_argument("--tags", default="imported", help="Comma-separated tags for the meta field")
    parser.add_argument("--folders", help="Optional JSON manifest mapping chat IDs to folder names")
    parser.add_argument("--folder-tag-prefix", default="project:", help="Prefix for project tags")
    parser.add_argument("--schema-db", help="Path to a webui.db file for schema detection")
    parser.add_argument("--output", help="Write SQL statements to this file")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(',') if t.strip()] or ["imported"]
    folder_map = load_folder_manifest(args.folders)
    chat_columns = load_table_columns(args.schema_db, "chat")
    folder_columns = load_table_columns(args.schema_db, "folder")

    files = gather_files(args.files)
    inserts = []
    folder_inserts = []
    user_ids: set[str] = set()
    tag_names: set[str] = set()
    folders: dict[tuple[str, str], dict[str, object]] = {}
    for fpath in files:
        try:
            sql, uid, folder_name, folder_id, chat_tags, created_at = json_to_sql(
                fpath,
                tags,
                args.folder_tag_prefix,
                folder_map,
                chat_columns,
            )
            inserts.append(sql)
            user_ids.add(uid)
            tag_names.update(chat_tags)
            if folder_name and folder_id:
                key = (uid, folder_name)
                entry = folders.get(key)
                if entry is None:
                    folders[key] = {"id": folder_id, "created_at": created_at}
                else:
                    entry["created_at"] = min(int(entry["created_at"]), created_at)
        except Exception as exc:
            raise SystemExit(f"Failed to process {fpath}: {exc}")

    prefix = []
    for uid in sorted(user_ids):
        prefix.extend(tag_upserts(uid, sorted(tag_names)))

    for (uid, folder_name), entry in sorted(folders.items()):
        folder_inserts.append(
            build_folder_insert(
                folder_id=str(entry["id"]),
                folder_name=folder_name,
                user_id=uid,
                created_at=int(entry["created_at"]),
                columns=folder_columns,
            )
        )

    output = "\n".join(prefix + folder_inserts + inserts)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
