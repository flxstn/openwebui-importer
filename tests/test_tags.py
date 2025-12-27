import create_sql


def test_tag_upserts_uses_insert_or_ignore():
    stmts = create_sql.tag_upserts("user-1", ["project:Demo"], {"id", "name", "user_id", "meta"})
    assert any("INSERT OR IGNORE" in stmt for stmt in stmts)
    assert all("ON CONFLICT" not in stmt for stmt in stmts)
