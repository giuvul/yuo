# UI languages

Every text in the web app is a Lingui message with an explicit dotted id (`wizard.step.computer`),
written in English in the code and collected into `en/messages.po`. A language is one PO catalog
in a folder named after its language tag.

## Adding a language

1. **Add the catalog.** Create the folder (for example `de/`), then run `npm run i18n:extract`:
   it writes `de/messages.po` with every id and the English text as the reference. Fill in each
   `msgstr`. Keep the placeholders (`{name}`, `#`, `<0>…</0>`) exactly as they are.
2. **Add it to `locales` in `src/i18n.ts`**: one entry in `LOCALES`, with the loader
   `() => import("./locales/de/messages.po")`.
3. **Give it its name in its own language** in that entry (`name: "Deutsch"`). The language
   picker in Settings and in the setup wizard lists it from then on.

`npm run i18n:check` fails while a catalog misses a translation or an id the code uses. Lingui's
config and the check script find the catalog folders by themselves.

The learner's choice is stored with their profile (`ui_lang` in `/api/me`) and applied when the
app loads. The consent texts for Claude Code and Codex (`wizard.consent.*`) are agreements: translate
them faithfully; the English original stays the one that is recorded.
