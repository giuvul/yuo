# Yuo path package format, version 1.0

- Status: **1.0** (2026-10-29), from draft 0.1 (2026-10-21). Implemented in `yuo/sharing/` (format) and
  `yuo/app/sharing.py` (an install's paths in and out). Packages hold no executable content: scene code never
  travels. From 1.0 on, a breaking change needs a new major version and an upgrader.
- The key words MUST, MUST NOT, SHOULD, MAY are used as in RFC 2119.
- Machine-readable parts: `spec/schemas/*.schema.json` (JSON Schema 2020-12), generated from the record
  models in `yuo/sharing/records.py` (`scripts/gen_package_schemas.py`, checked in CI). Where this text and
  the schemas differ, the schemas win. Conformance fixtures: `spec/fixtures/` (section 14).

## 1. Scope

A **package** is a `.zip` file carrying one path (or components of one path) between installations,
independent of any database. The same container serves three uses:

| Use | Profile | Typical content |
|---|---|---|
| Share a path to be regenerated on the recipient's models | `structure` | Tree, objectives, lesson bodies or scripts, items |
| Share a ready-to-study path | `full` | `structure` plus rendered videos, audio, images, readings, sources |
| Export selected components | `custom` | Any subset, e.g. only quizzes, only videos, optionally with standard-format files (MP4, `.apkg`, QTI) |

Out of scope: the learner's personal record (events, progress, conversations, notes). That is the
**data export**, a separate format. Packages MUST NOT contain data of class P; class F
content is limited to section 7.

## 2. Container

```
my-path.yuo.zip
├── yuo.json                     manifest (section 3), REQUIRED, first entry in the zip
├── records/                     one JSON Lines file per entity kind (section 5)
│   ├── path.jsonl
│   ├── branch.jsonl
│   ├── skill.jsonl
│   ├── objective.jsonl
│   ├── lesson.jsonl
│   ├── rendition.jsonl
│   ├── item.jsonl
│   ├── source.jsonl
│   ├── asset.jsonl
│   └── theme.jsonl              optional (video themes only)
├── assets/sha256/<hex>          binary assets addressed by hash, no extension
├── standard/                    optional standard-format copies (section 9), e.g. videos/*.mp4, flashcards.apkg
└── yuo.sig                      optional detached signature (section 10)
```

Rules:

- **Records** are JSON Lines: UTF-8, one record per line, each line the RFC 8785 (JCS) canonical
  form of the record, lines sorted by `code` (then `version_no` where present), trailing newline.
  Two exports of the same content are byte-identical, so packages diff cleanly in git.
- **Paths** inside the zip are relative, `/`-separated, NFC-normalised UTF-8, at most 255 bytes,
  matching `^[A-Za-z0-9._/-]+$`. No `..` segments, no absolute paths, no symlinks, no directories
  entries outside the layout above.
- **Compression**: deflate or stored. Assets that are already compressed (MP4, PNG, JPEG, WebP,
  Opus, M4A) SHOULD be stored.
- **Every file except `yuo.json` and `yuo.sig` MUST appear in the manifest inventory**; files not in
  the inventory make the package invalid.

## 3. Manifest (`yuo.json`)

```json
{
  "format": "yuo.package",
  "format_version": "1.0.0",
  "package_uid": "pkg_01JB9Q4Y8V3K2M7N5P0R6S1T2V",
  "content_version": "1.2.0",
  "profile": "full",
  "contents": ["curriculum", "lessons", "renditions.video", "items", "sources", "assets"],
  "title": "SQL for analysts",
  "content_lang": "en",
  "licence": "CC-BY-SA-4.0",
  "licences_used": ["CC-BY-SA-4.0", "CC-BY-4.0"],
  "authors": [{"name": "A. Curator", "role": "curator"}],
  "parent_package_digest": null,
  "translation_of_package_uid": null,
  "created_with": {"app": "yuo", "version": "0.3.0"},
  "created_at": "2026-10-21T09:00:00Z",
  "required_exercise_types": [{"key": "mcq", "version": 1}, {"key": "cloze", "version": 1}],
  "inventory": {
    "files": [{"path": "records/skill.jsonl", "sha256": "…", "bytes": 18234}],
    "counts": {"by_kind": {"skill": 24, "lesson": 24, "item": 180}, "by_data_class": {"C": 228, "F": 0}},
    "total_bytes": 412345678
  },
  "extensions": {}
}
```

| Field | Rule |
|---|---|
| `format` | Constant `yuo.package`. Lets importers recognise the file without trusting the extension. |
| `format_version` | Semver of **this spec**. Major change = upgrader required; minor = additive; patch = clarification. |
| `package_uid` | Stable identity of the shared path across all its content versions: `pkg_` + 26 lowercase base32 characters, generated at first export. A re-export whose record files are unchanged keeps it (also after a round trip through another install); a changed re-export of a path that came from someone else's package is a **fork**: new uid, `parent_package_digest` set. |
| `content_version` | Semver for the path content: unchanged records keep it; a changed re-export of the path's own package bumps the minor (the author MAY choose patch or major). Drives the update prompt on re-import. |
| `profile` | `structure`, `full`, `custom`. |
| `contents` | Component tags present (section 8). The importer's content detection reads this first, then verifies it against `records/`. |
| `licence` | SPDX expression for the path. Records without their own `licence` inherit it. `licences_used` is the computed set of every licence in the package. |
| `parent_package_digest` | Digest of the package this one was forked from; attribution chain. |
| `translation_of_package_uid` | Set when the path is a translation (one language per path). |
| `required_exercise_types` | Exercise types the items use. Unknown types are imported and preserved, but not playable (section 6). |
| `inventory.files` | Every file with SHA-256 and size. |
| `inventory.counts` | Records per kind and per data class (C, F). |
| `extensions` | Namespaced (section 11). |

**Package digest** = SHA-256 of the JCS form of `yuo.json` with `extensions` kept and nothing
removed. Because the inventory lists every file hash, the digest identifies the whole package. It is
stored in `package_record.package_digest` on both sides.

## 4. Identity and references

- Records use **codes**, never local ids. Codes are unique per (path, entity kind), stable across
  versions and packages, and never reused. Pattern: `^[a-z0-9]+([._-][a-z0-9]+)*$`, at most 128 chars.
- References inside records, including inside JSON payloads (lesson bodies, item payloads, scene
  specs), are typed ref objects `{"kind": "<entity_kind>", "code": "<code>"}`; to a specific version
  `{"kind": …, "code": …, "version_hash": …}`; to an asset `{"kind": "asset", "sha256": …}`; to a source
  `{"kind": "source", "key": …}`. Fields that hold refs are marked with `x-ref` in the record schemas,
  so importers can rewrite them without knowing the payload type.
- A ref to a code not present in the package is allowed only for profile `custom` and is reported
  as **dangling**; on import into an existing path it is resolved through `import_map`, otherwise
  the referencing record is imported with the ref kept and flagged.

## 5. Records

Each kind has a head record with its versions inline. Common fields:

| Field | Rule |
|---|---|
| `code` | REQUIRED (section 4). |
| `position` | Sibling order (int). |
| `archived` | bool; archived entities are exported only if still referenced. |
| `extensions` | Namespaced object, preserved on round-trip. |
| `current` | `version_hash` of the current version (versioned kinds). |
| `versions` | Array of version records; by default only the current one, all with the "full history" option. |

Version records (lesson, rendition, item):

| Field | Rule |
|---|---|
| `version_hash` | SHA-256 of the JCS form of the **hashed content** of the version (table below). Importers MUST recompute it and reject mismatches. |
| `version_no` | The version's position (1-based) among the versions exported for its head, so it is the same on every install. Informative. |
| `lang` | BCP 47; MUST equal the path's `content_lang`. |
| `translation_of_version_hash` | Optional. |
| `provenance` | `authorship`, `author_kind`, `author_ref?`, `licence?`, `upstream?` (package_uid, code, version_hash, authorship, `generated_by`: model and prompt summary), `derived_from_version_hash?`. Not part of the hash. |
| `quality` | Optional summary of the exporter's checks (`check`, `verdict`, `at`). Informative: the importer re-runs deterministic checks. |

Hashed content per kind (fields not listed are not hashed, so the same content produced by two
routes has the same hash):

| Kind | Hashed content |
|---|---|
| lesson version | `lang`, `title`, `body` (lesson_body schema id + version + document), `est_minutes`, `objectives` (codes + roles, sorted), `sources` (keys + locators + block ids, sorted) |
| item version | `type_key`, `type_version`, `lang`, `difficulty`, `payload`, `support`, `objectives` (sorted), `resets_review` |
| rendition version | `kind`, `lang`, `lesson_version_hash`, `renderer`, `spec_kind`, `narration`, `theme` (code or null), `voice`, `assets` (role, lang, `recipe_hash`, sorted) |

The asset's own hash is **not** in the rendition hash: re-renders are not byte-identical, so
identity follows the recipe (`rendition_asset.recipe_hash`).

Per-kind fields (beyond the common ones):

| Kind | Fields |
|---|---|
| `path` (exactly one) | `title`, `subject`, `goal`, `goal_type`, `difficulty`, `content_lang`, `licence`, `authors`. Never `learner`, `status`, `target_date` (personal). |
| `branch` | `title` |
| `skill` | `branch` (code), `title`, `summary`, `prerequisites` (skill codes; DAG), `mastery_threshold?`, `optional`, `merged_into?` |
| `objective` | `skill` (code), `statement`, `bloom_level?` |
| `lesson` | `skill` (code), `kind` (`core`, `remedial`; `requested` only with section 7 opt-in), versions |
| `rendition` | `code` = `<lesson code>.<kind>` (one rendition per kind per lesson), `lesson` (code), `kind` (`reading`, `video`, `slides`, `audio`), versions. Version fields: `spec_kind` = `rendered` (the only value in 1.0), `narration` (timeline and segments), `voice`, `duration_s`, `assets` (role, lang, `recipe_hash`, `sha256`). |
| `item` | `skill` (code), `type_key`, versions. Version fields: `type_version`, `difficulty`, `payload`, `support`, `objectives` (codes), `resets_review`, `origin_lesson` (code, optional). |
| `source` | `key` (its identity, instead of `code`), `kind`, `title`, `url?`, `accessed_at?`, `published_at?`, `citation` (CSL-JSON) |
| `asset` | `sha256`, `media_type`, `kind`, `bytes`, `present` (false when the bytes were left out, e.g. profile `structure`) |
| `theme` | `kind` = `video`, `name`, `tokens` (W3C design tokens) |

Videos travel as rendered media only: the MP4, its WebVTT captions and a poster, as assets, with
`spec_kind = rendered` and no `spec`. Model-written scene code is never exported (section 10):
the importer plays the video it receives and cannot re-render it. Never exported: scene code, versions
made from personal inputs or by the learner (unless opted in, section 7), quality check details, stage
runs and raw model outputs, prompt templates, settings, UI themes.

Every version record carries `provenance` (not hashed): `authorship`, `author_kind`, `licence?`,
`upstream?`, `generated_by?` (`{"model": ...}`, never the prompt). An importer stores provenance and any
version fields it does not model as they came and writes them back unchanged, and `data_class` (`C`, or
`F` for opted-in personal content, section 7).

## 6. Exercise types

- Item payloads validate against the exercise type's payload schema `(type_key, type_version)`.
  Built-in types ship their schemas under `spec/schemas/exercise/`.
- An unknown type or a newer major version is imported with `exercise_type.status = unsupported`:
  the item is preserved byte for byte, excluded from practice, and re-exported unchanged.
- An older version is upgraded by the exercise type's own upgrader.

## 7. Personal and learner-authored content

- **Never included:** class P data.
- **Off by default, explicit checkbox per group, listed in the export preview:**
  learner-authored or learner-edited items (flashcards), `requested` lessons and their
  renditions, learner uploads used as sources or assets. Records included this way carry
  `data_class: "F"` and are counted in `inventory.counts.by_data_class.F`; the import preview shows them.
- Free text in the path record (`goal`) is reviewed in the preview, since learners often write
  personal context there.

## 8. Components and content detection

| Tag | Present when |
|---|---|
| `curriculum` | `path`, `branch`, `skill`, `objective` records |
| `lessons` | `lesson` records with versions |
| `renditions.reading`, `renditions.video`, `renditions.audio`, `renditions.slides` | rendition records of that kind |
| `items` | `item` records (any type) |
| `flashcards` | items of type `flashcard` (also tagged `items`) |
| `sources` | `source` records |
| `assets` | at least one asset with `present: true` |
| `themes` | `theme` records |
| `standard.<format>` | files under `standard/` (section 9) |

Import offers, based on what is present: **new path** (requires `curriculum`), or **merge into an
existing path** (matched by `package_uid` through `import_map`, or chosen by the learner, then
matched by code). Component packages without `curriculum` MUST be merged into an existing path or
attached to a placeholder skill the importer creates.

## 9. Standard-format files

Component exports MAY add standard files under `standard/`, each listed in the inventory
with a `represents` mapping in `extensions["yuo:standard"]`:

```json
{"yuo:standard": [{"path": "standard/flashcards.apkg", "format": "anki-apkg", "represents": {"kind": "item", "codes": ["sql.joins.c1", "…"]}}]}
```

The records stay authoritative: on re-import of a Yuo package the standard files are ignored when
the records are present. Standard files **without** a manifest (a bare `.apkg`, QTI, Moodle XML,
CSV) are handled by import adapters, outside this spec.

v1 set (format ids): `csv` (`items.csv`, `flashcards.csv`), `anki` (`flashcards.apkg`), `moodle`
(`questions.xml`), `readings` (Markdown and HTML per lesson), `video` (MP4, WebVTT and poster per
lesson), `bibtex` (`sources.bib`), `csljson` (`sources.json`). QTI and a static site: v1.x.

## 10. Integrity, signatures and trust

- Importers MUST verify every inventory hash and size, recompute every `version_hash`, and reject
  the package on any mismatch (no partial import).
- `yuo.sig` MAY hold a Sigstore bundle over the package digest. Verification arrives with release
  signing; until then a signed package is accepted and shown as unsigned, with a notice.
- Every package is **untrusted input**:
  - no executable content: no scripts, HTML, SVG, macros, or agent-coded scenes;
  - text fields are plain text; rich text only as lesson_body inline marks; link targets limited to
    `https:`, `http:`, `mailto:`; mermaid diagram sources rendered in the sandboxed renderer;
  - allowed media types: PNG, JPEG, WebP, GIF (static) images; MP4 (H.264/AAC) and WebM video;
    M4A, Opus, MP3 audio; WebVTT subtitles; PDF documents (shown in a sandboxed viewer);
    media type is sniffed from bytes and MUST match `media_type`;
  - limits (defaults, configurable): 10 GB uncompressed, 20,000 files, 50 MB per record file,
    compression ratio above 100:1 on any entry larger than 1 KB rejects the package (zip bomb); an entry
    is never read past its declared size; a 5-minute lesson video is about 6 to 12 MB;
  - SVG and every media type not in the list above are refused;
  - text from packages is data for the tutor and the generator, never instructions.

## 11. Extensions and forward compatibility

- Extension keys are namespaced: `yuo:*` reserved for this project, others `x-<org>:<name>` or a
  reverse-DNS prefix. Values are JSON.
- Importers MUST preserve extensions and **unknown fields** they do not understand: unknown fields of
  a record are stored with the entity (`extensions["yuo:unknown"]`) and written back in place on export.
- Importers MUST accept packages with a newer **minor** version (ignoring and preserving what is
  new) and MUST refuse a newer **major** version with a clear message.
- Older majors are upgraded by a chain of pure upgraders, each a JSON-to-JSON function with golden
  fixtures. `0.1 → 1.0` drops rendition versions that carry a scene spec (declarative or agent
  code); the lesson keeps its reading.

## 12. Licences and attribution

- Every package states a path licence (SPDX). Records MAY override it.
- The exporter computes `licences_used` from provenance and refuses known-incompatible combinations
  (for example an SA licence combined with a non-derivative one) or asks the author to resolve them.
- `provenance.upstream` is preserved across hops, so a fork of a fork still credits the original.
  Generated content carries `authorship: generated` and a model and prompt summary, never
  the raw prompt.

## 13. Import algorithm (informative)

1. Open the zip safely (section 10 limits), read `yuo.json`, check `format` and `format_version`
   (upgrade if older major, refuse if newer major).
2. Verify inventory hashes; parse records; validate against the record schemas.
3. Recompute version hashes; recheck the skill DAG; sniff asset media types.
4. Look up `package` by `package_uid`: unknown → offer new path; known → offer update (shows
   `content_version` change) or new copy (path code suffixed).
5. Map codes through `import_map` (`package_id`, `entity_kind`, `external_code`); rewrite `x-ref`
   fields to local ids.
6. For each versioned head: an unknown `version_hash` becomes a new version (`acquired_via = import`).
   It becomes current unless the local current is `human_edited` by the learner; then a
   `merge_conflict` is opened.
7. Re-run deterministic quality checks and store them as `quality_check` rows; imported versions
   pass the gate only through those checks (model review optional, CFG).
8. Write `package_record` (direction import) with the digest and the manifest.

All steps run in one transaction; failure leaves the database unchanged.

## 14. Conformance

- `spec/fixtures/` holds valid and invalid packages, with the reason each invalid one MUST be refused
  in `expected.json`: valid minimal, structure, full, custom-items-only, older-version (0.1),
  unknown-extension, unknown-exercise-type; invalid path-traversal, zip-bomb, hash-mismatch,
  not-listed, version-hash, svg-with-script, media-sniff, html-in-body, link-in-text, dag-cycle,
  newer-major, manifest-not-first. They are made by `scripts/gen_package_fixtures.py`.
- Round-trip test: import then export of every valid fixture yields byte-identical record files and
  an identical inventory; the manifest differs only in `created_at` and `created_with` (so the digest
  differs only through them).
- Property test: random paths generated from the record schemas round-trip. [OPEN: not built in 1.0;
  the fixtures and a generated path in every profile are tested instead.]

## 15. Open items

- Decided in 1.0: the v1 standard formats (section 9); `content_version` bumps the minor automatically
  when the records changed (section 3).
- [OPEN] Signature verification (with release signing).
- [ASSUMPTION] One path per package; multi-path bundles are out of v1.
