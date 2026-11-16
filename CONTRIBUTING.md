# Contributing to Yuo

Thank you for helping. Bug reports, ideas, translations, docs and code are all welcome. By taking part you agree
to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Report a bug**: open an issue with the bug form. Say what you did, what you expected and what happened, and
  add your Yuo version (Settings > Updates), how you run it (server version or desktop app) and the AI you use.
  Leave out keys, setup codes and personal data. Logs: `docker compose logs --since 10m yuo` on the server
  version, `logs/launcher.log` beside the data folder on the desktop app.
- **Suggest a feature**: open an issue with the feature form and describe the problem before the solution.
- **Translate**: the app is in English, Italian, Spanish, Portuguese and German. Catalogs live in
  `web/src/locales/<lang>/messages.po`; a new language needs every message translated.
- **Security issues**: never in a public issue. See [SECURITY.md](SECURITY.md).

For anything bigger than a small fix, open an issue first so we can agree on the approach before you write code.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Node.js LTS. uv installs the pinned Python (3.14), which ships the
SQLite version Yuo needs; the system Python is not used.

```sh
uv run scripts/dev.py      # installs locked dependencies, migrates a dev database, runs the API and the web app
```

You do not need a paid AI account to develop: the tests run on scripted models. To try real lessons, connect a
model in Yuo's setup (a local model server works).

## Checks

```sh
uv run scripts/ci.py         # everything CI runs
uv run scripts/ci.py --fast  # skips the web build and the SBOM diff
```

A pull request needs these green. They include ruff, mypy (strict), import-linter, pytest with the fitness
tests, the TypeScript check, Vitest, the translation check, the browser tests and the licence gate.

## How the code is organised

Read [docs/architecture.md](docs/architecture.md) first. The rules the checks enforce:

- **Contexts do not import each other.** The packages under `yuo/` meet through `yuo/core` and the application
  service; only `yuo/adapters` imports vendor SDKs or starts child processes, and GPL tools (ffmpeg, espeak-ng)
  run only as separate programs from `yuo/adapters/tools`.
- **The database schema is generated** from `yuo/db/rows.py`: change the row models, run
  `uv run scripts/gen_schema.py`, and add a new numbered migration. Never edit a migration that has shipped.
- **The API types are generated**: after an API change run `uv run scripts/export_openapi.py` and
  `npm run api:types` in `web/`.
- **Dependencies**: in-process dependencies must have a permissive or LGPL licence (`scripts/licence_gate.py`).
  A dependency change regenerates the SBOM: `uv run scripts/sbom.py`.
- **Tests never call paid providers** unless marked `live` and run with `YUO_LIVE=1`.

## Web app conventions

- **Every visible string** goes through Lingui with an explicit id (lowercase, dotted, for example
  `settings.video.title`) and is translated in all five catalogs in the same pull request.
- **Styling** uses CSS Modules and the semantic design tokens in `web/src/styles/tokens.css`, never raw colours
  or sizes. Every screen must work in light and dark themes and at phone width.
- **Accessibility**: use the React Aria components already in the app, keep keyboard access and visible focus.
- **Motion** is CSS only and respects reduced motion.
- **Formatting**: keep the style of the file you are editing and keep diffs small. Do not run a formatter over
  the web code; Python is formatted with `ruff format`.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep one change per pull request, with tests for new behaviour and for the bug you fix.
3. Update the docs and [CHANGELOG.md](CHANGELOG.md) (under "Unreleased") when users will notice the change.
4. Write commit messages in the imperative ("Add the Anki export"), with the why in the body when it is not
   obvious.
5. Fill in the pull request template and make sure the checks pass.

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE), the
project's licence.
