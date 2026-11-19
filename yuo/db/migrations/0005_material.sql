-- 0005_material: the plan preview before a path is built, and learning from the learner's own material:
-- courses, their material (files and links), the material's sections and chunks with a search index, the
-- chunks each skill is built on, related skills across courses, and the chunks an item was written from.
CREATE TABLE course (
  id                           TEXT PRIMARY KEY NOT NULL CHECK (length(id)=36 AND substr(id,15,1)='7' AND id=lower(id)),
  path_id                      TEXT NOT NULL CHECK (length(path_id)=36 AND substr(path_id,15,1)='7' AND path_id=lower(path_id)) REFERENCES path(id),
  code                         TEXT NOT NULL,
  title                        TEXT NOT NULL,
  term                         TEXT,
  exam_date                    TEXT CHECK (exam_date = date(exam_date)),
  adherence                    TEXT NOT NULL CHECK (adherence IN ('only','grounded','open')),
  keep_order                   INTEGER NOT NULL CHECK (keep_order IN (0,1)),
  position                     INTEGER NOT NULL CHECK (position >= 0),
  branch_id                    TEXT CHECK (length(branch_id)=36 AND substr(branch_id,15,1)='7' AND branch_id=lower(branch_id)) REFERENCES branch(id),
  outline                      TEXT CHECK (json_valid(outline)),
  extensions                   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extensions)),
  created_at                   TEXT NOT NULL CHECK (created_at = strftime('%Y-%m-%dT%H:%M:%fZ', created_at)),
  archived_at                  TEXT CHECK (archived_at = strftime('%Y-%m-%dT%H:%M:%fZ', archived_at)),
  UNIQUE (path_id, code)
) STRICT;

CREATE TABLE item_version_source (
  item_version_id              TEXT NOT NULL CHECK (length(item_version_id)=36 AND substr(item_version_id,15,1)='7' AND item_version_id=lower(item_version_id)) REFERENCES item_version(id),
  section_id                   TEXT NOT NULL CHECK (length(section_id)=36 AND substr(section_id,15,1)='7' AND section_id=lower(section_id)) REFERENCES material_section(id),
  PRIMARY KEY (item_version_id, section_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE material (
  id                           TEXT PRIMARY KEY NOT NULL CHECK (length(id)=36 AND substr(id,15,1)='7' AND id=lower(id)),
  path_id                      TEXT NOT NULL CHECK (length(path_id)=36 AND substr(path_id,15,1)='7' AND path_id=lower(path_id)) REFERENCES path(id),
  course_id                    TEXT NOT NULL CHECK (length(course_id)=36 AND substr(course_id,15,1)='7' AND course_id=lower(course_id)) REFERENCES course(id),
  source_id                    TEXT NOT NULL CHECK (length(source_id)=36 AND substr(source_id,15,1)='7' AND source_id=lower(source_id)) REFERENCES source(id),
  "role"                       TEXT NOT NULL CHECK ("role" IN ('textbook','slides','lecture','notes','exercises','exams','other')),
  kind                         TEXT NOT NULL CHECK (kind IN ('pdf','pptx','docx','text','audio','video','link')),
  title                        TEXT NOT NULL,
  file_name                    TEXT,
  asset_hash                   TEXT CHECK (length(asset_hash)=64 AND asset_hash NOT GLOB '*[^0-9a-f]*'),
  size_bytes                   INTEGER NOT NULL CHECK (size_bytes >= 0),
  pages                        INTEGER CHECK (pages >= 0),
  duration_ms                  INTEGER CHECK (duration_ms >= 0),
  keep_original                INTEGER NOT NULL CHECK (keep_original IN (0,1)),
  state                        TEXT NOT NULL CHECK (state IN ('uploading','reading','read','transcribing','digesting','outlining','ready','failed')),
  progress                     REAL NOT NULL CHECK (progress BETWEEN 0 AND 1),
  error                        TEXT,
  outline                      TEXT CHECK (json_valid(outline)),
  position                     INTEGER NOT NULL CHECK (position >= 0),
  extensions                   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extensions)),
  created_at                   TEXT NOT NULL CHECK (created_at = strftime('%Y-%m-%dT%H:%M:%fZ', created_at)),
  updated_at                   TEXT NOT NULL CHECK (updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', updated_at))
) STRICT;

CREATE TABLE material_section (
  id                           TEXT PRIMARY KEY NOT NULL CHECK (length(id)=36 AND substr(id,15,1)='7' AND id=lower(id)),
  material_id                  TEXT NOT NULL CHECK (length(material_id)=36 AND substr(material_id,15,1)='7' AND material_id=lower(material_id)) REFERENCES material(id),
  parent_id                    TEXT CHECK (length(parent_id)=36 AND substr(parent_id,15,1)='7' AND parent_id=lower(parent_id)) REFERENCES material_section(id),
  position                     INTEGER NOT NULL CHECK (position >= 0),
  level                        TEXT NOT NULL CHECK (level IN ('part','chapter','section','chunk')),
  title                        TEXT NOT NULL,
  loc_kind                     TEXT NOT NULL CHECK (loc_kind IN ('page','slide','time')),
  loc_start                    INTEGER NOT NULL CHECK (loc_start >= 0),
  loc_end                      INTEGER NOT NULL CHECK (loc_end >= 0),
  "text"                       TEXT,
  tokens                       INTEGER NOT NULL CHECK (tokens >= 0),
  digest                       TEXT CHECK (json_valid(digest)),
  content_hash                 TEXT CHECK (length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
  UNIQUE (material_id, position)
) STRICT;

CREATE TABLE skill_anchor (
  skill_id                     TEXT NOT NULL CHECK (length(skill_id)=36 AND substr(skill_id,15,1)='7' AND skill_id=lower(skill_id)),
  section_id                   TEXT NOT NULL CHECK (length(section_id)=36 AND substr(section_id,15,1)='7' AND section_id=lower(section_id)) REFERENCES material_section(id),
  path_id                      TEXT NOT NULL CHECK (length(path_id)=36 AND substr(path_id,15,1)='7' AND path_id=lower(path_id)) REFERENCES path(id),
  "role"                       TEXT NOT NULL CHECK ("role" IN ('primary','supporting')),
  PRIMARY KEY (skill_id, section_id),
  FOREIGN KEY (skill_id, path_id) REFERENCES skill (id, path_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE skill_link (
  skill_id                     TEXT NOT NULL CHECK (length(skill_id)=36 AND substr(skill_id,15,1)='7' AND skill_id=lower(skill_id)),
  other_skill_id               TEXT NOT NULL CHECK (length(other_skill_id)=36 AND substr(other_skill_id,15,1)='7' AND other_skill_id=lower(other_skill_id)),
  path_id                      TEXT NOT NULL CHECK (length(path_id)=36 AND substr(path_id,15,1)='7' AND path_id=lower(path_id)) REFERENCES path(id),
  kind                         TEXT NOT NULL CHECK (kind IN ('related')),
  note                         TEXT,
  PRIMARY KEY (skill_id, other_skill_id),
  FOREIGN KEY (skill_id, path_id) REFERENCES skill (id, path_id),
  FOREIGN KEY (other_skill_id, path_id) REFERENCES skill (id, path_id),
  CHECK (skill_id <> other_skill_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX course_path ON course (path_id, position);
CREATE INDEX material_course ON material (course_id, position);
CREATE INDEX material_path ON material (path_id);
CREATE INDEX material_section_parent ON material_section (parent_id);
CREATE INDEX skill_anchor_section ON skill_anchor (section_id);
CREATE INDEX item_version_source_section ON item_version_source (section_id);
CREATE VIRTUAL TABLE material_fts USING fts5(
  title, text, content='material_section', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
INSERT INTO material_fts (material_fts, rank) VALUES ('secure-delete', 1);
CREATE TRIGGER material_section_ai AFTER INSERT ON material_section WHEN NEW.text IS NOT NULL BEGIN
  INSERT INTO material_fts (rowid, title, text) VALUES (NEW.rowid, NEW.title, NEW.text);
END;
CREATE TRIGGER material_section_ad AFTER DELETE ON material_section WHEN OLD.text IS NOT NULL BEGIN
  INSERT INTO material_fts (material_fts, rowid, title, text) VALUES ('delete', OLD.rowid, OLD.title, OLD.text);
END;
CREATE TRIGGER material_section_au AFTER UPDATE OF title, text ON material_section BEGIN
  INSERT INTO material_fts (material_fts, rowid, title, text) SELECT 'delete', OLD.rowid, OLD.title, OLD.text WHERE OLD.text IS NOT NULL;
  INSERT INTO material_fts (rowid, title, text) SELECT NEW.rowid, NEW.title, NEW.text WHERE NEW.text IS NOT NULL;
END;

INSERT INTO entity_kind_ref ("key") VALUES ('course');
INSERT INTO entity_kind_ref ("key") VALUES ('material');
INSERT INTO stage_kind ("key") VALUES ('course_links');
INSERT INTO stage_kind ("key") VALUES ('course_outline');
INSERT INTO stage_kind ("key") VALUES ('course_revise');
INSERT INTO stage_kind ("key") VALUES ('material_digest');
INSERT INTO stage_kind ("key") VALUES ('material_outline');
INSERT INTO stage_kind ("key") VALUES ('tree_revise');

-- three new job kinds: generation_job.kind's CHECK only gains values, so every existing row still passes. SQLite
-- cannot change a CHECK in place; widening it in the stored schema is the documented way ("Making Other Kinds
-- Of Table Schema Changes" in SQLite's ALTER TABLE page). The migration runner bumps schema_version after it.
PRAGMA writable_schema = ON;
UPDATE sqlite_schema SET sql = replace(sql, '''grade'',''request'')', '''grade'',''request'',''material'',''course'',''course_links'')') WHERE type = 'table' AND name = 'generation_job';
PRAGMA writable_schema = OFF;
