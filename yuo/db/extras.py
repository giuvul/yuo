"""Schema objects that are not columns: indexes, search, cross-row triggers."""

EXTRA: list[str] = [
    # partial indexes where most rows are inert
    "CREATE INDEX generation_job_runnable ON generation_job (next_attempt_at)\n"
    "WHERE status IN ('queued','waiting_resource');",
    "CREATE UNIQUE INDEX stage_run_inflight ON stage_run (input_hash)\n"
    "WHERE status IN ('queued','waiting_resource','running');",
    "CREATE INDEX stage_run_cache ON stage_run (input_hash) WHERE status = 'succeeded';",
    "CREATE INDEX learning_event_item_version ON learning_event (item_version_id)\n"
    "WHERE item_version_id IS NOT NULL;",
    "CREATE INDEX learning_event_learner_order ON learning_event (learner_id, device_at, id);",
    "CREATE INDEX asset_live ON asset (kind, created_at) WHERE evicted_at IS NULL;",
    "CREATE INDEX message_streaming ON message (conversation_id) WHERE status = 'streaming';",
    "CREATE INDEX message_conversation ON message (conversation_id, created_at);",
    "CREATE INDEX asset_ref_owner ON asset_ref (owner_kind, owner_id);",
    # same-lesson rule for renditions (a CHECK cannot hold a subquery)
    "CREATE TRIGGER rendition_version_same_lesson BEFORE INSERT ON rendition_version\n"
    "WHEN NOT EXISTS (SELECT 1 FROM lesson_version lv JOIN rendition r ON r.lesson_id = lv.lesson_id\n"
    "                 WHERE r.id = NEW.rendition_id AND lv.id = NEW.lesson_version_id)\n"
    "BEGIN SELECT RAISE(ABORT, 'rendition_version must present a version of its own lesson'); END;",
    # search: external-content FTS5 over lesson_search_doc, secure-delete on
    "CREATE VIRTUAL TABLE lesson_fts USING fts5(\n"
    "  title, body, content='lesson_search_doc', content_rowid='docid',\n"
    "  tokenize='unicode61 remove_diacritics 2', prefix='2 3'\n);",
    "INSERT INTO lesson_fts (lesson_fts, rank) VALUES ('secure-delete', 1);",
    "CREATE TRIGGER lesson_search_doc_ai AFTER INSERT ON lesson_search_doc BEGIN\n"
    "  INSERT INTO lesson_fts (rowid, title, body) VALUES (NEW.docid, NEW.title, NEW.body);\nEND;",
    "CREATE TRIGGER lesson_search_doc_ad AFTER DELETE ON lesson_search_doc BEGIN\n"
    "  INSERT INTO lesson_fts (lesson_fts, rowid, title, body) VALUES ('delete', OLD.docid, OLD.title, OLD.body);\nEND;",
    "CREATE TRIGGER lesson_search_doc_au AFTER UPDATE ON lesson_search_doc BEGIN\n"
    "  INSERT INTO lesson_fts (lesson_fts, rowid, title, body) VALUES ('delete', OLD.docid, OLD.title, OLD.body);\n"
    "  INSERT INTO lesson_fts (rowid, title, body) VALUES (NEW.docid, NEW.title, NEW.body);\nEND;",
]

# Objects added by later migrations (the key is the migration number); 0001 above never changes.
LATER: dict[int, list[str]] = {
    5: [
        "CREATE INDEX course_path ON course (path_id, position);",
        "CREATE INDEX material_course ON material (course_id, position);",
        "CREATE INDEX material_path ON material (path_id);",
        "CREATE INDEX material_section_parent ON material_section (parent_id);",
        "CREATE INDEX skill_anchor_section ON skill_anchor (section_id);",
        "CREATE INDEX item_version_source_section ON item_version_source (section_id);",
        # search over the material's chunks: external-content FTS5 on material_section (chunks only)
        "CREATE VIRTUAL TABLE material_fts USING fts5(\n"
        "  title, text, content='material_section', content_rowid='rowid',\n"
        "  tokenize='unicode61 remove_diacritics 2'\n);",
        "INSERT INTO material_fts (material_fts, rank) VALUES ('secure-delete', 1);",
        "CREATE TRIGGER material_section_ai AFTER INSERT ON material_section WHEN NEW.text IS NOT NULL BEGIN\n"
        "  INSERT INTO material_fts (rowid, title, text) VALUES (NEW.rowid, NEW.title, NEW.text);\nEND;",
        "CREATE TRIGGER material_section_ad AFTER DELETE ON material_section WHEN OLD.text IS NOT NULL BEGIN\n"
        "  INSERT INTO material_fts (material_fts, rowid, title, text) VALUES ('delete', OLD.rowid, OLD.title, OLD.text);\nEND;",
        "CREATE TRIGGER material_section_au AFTER UPDATE OF title, text ON material_section BEGIN\n"
        "  INSERT INTO material_fts (material_fts, rowid, title, text) SELECT 'delete', OLD.rowid, OLD.title, OLD.text WHERE OLD.text IS NOT NULL;\n"
        "  INSERT INTO material_fts (rowid, title, text) SELECT NEW.rowid, NEW.title, NEW.text WHERE NEW.text IS NOT NULL;\nEND;",
    ],
    3: [
        # review sessions look questions up by objective (item_version_objective's key starts with the version)
        "CREATE INDEX item_version_objective_objective ON item_version_objective (objective_id);",
        "CREATE INDEX objective_review_state_due ON objective_review_state (learner_id, due_at);",
    ],
}
