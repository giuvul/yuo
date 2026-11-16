-- 0004_next_steps: the "What next?" checkpoint that grows a path (0.8.0). Its state lives in
-- path.extensions; only its three generation stages are new.
INSERT INTO stage_kind ("key") VALUES ('next_check');
INSERT INTO stage_kind ("key") VALUES ('next_directions');
INSERT INTO stage_kind ("key") VALUES ('next_grow');
