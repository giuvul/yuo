-- 0003_review: objective-level review memory and the review question bank (M7b).
-- The statements below are `uv run scripts/gen_schema.py --print 3`.
CREATE TABLE objective_review_state (
  learner_id                   TEXT NOT NULL CHECK (length(learner_id)=36 AND substr(learner_id,15,1)='7' AND learner_id=lower(learner_id)) REFERENCES learner(id),
  objective_id                 TEXT NOT NULL CHECK (length(objective_id)=36 AND substr(objective_id,15,1)='7' AND objective_id=lower(objective_id)) REFERENCES learning_objective(id),
  scheduler                    TEXT NOT NULL,
  state                        TEXT NOT NULL CHECK (json_valid(state)),
  due_at                       TEXT NOT NULL CHECK (due_at = strftime('%Y-%m-%dT%H:%M:%fZ', due_at)),
  last_review_at               TEXT CHECK (last_review_at = strftime('%Y-%m-%dT%H:%M:%fZ', last_review_at)),
  reviews                      INTEGER NOT NULL CHECK (reviews >= 0),
  lapses                       INTEGER NOT NULL CHECK (lapses >= 0),
  algo_version                 INTEGER NOT NULL CHECK (algo_version >= 1),
  inputs_hash                  TEXT NOT NULL CHECK (length(inputs_hash)=64 AND inputs_hash NOT GLOB '*[^0-9a-f]*'),
  rebuilt_at                   TEXT NOT NULL CHECK (rebuilt_at = strftime('%Y-%m-%dT%H:%M:%fZ', rebuilt_at)),
  PRIMARY KEY (learner_id, objective_id)
) STRICT;

CREATE INDEX item_version_objective_objective ON item_version_objective (objective_id);
CREATE INDEX objective_review_state_due ON objective_review_state (learner_id, due_at);

INSERT INTO stage_kind ("key") VALUES ('review_bank');
