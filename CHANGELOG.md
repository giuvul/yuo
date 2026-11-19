# Changelog

All notable changes are listed here. The format follows Keep a Changelog; versions follow SemVer.

## [Unreleased]

## [1.2.0] - 2026-11-19

- Generation can be paused: everything written ahead (lessons, videos, review questions, lessons you asked for)
  or only videos, for an hour, until tomorrow morning or until you resume, from the jobs page. Nothing done so
  far is lost: a job stops before its next model call and goes on from the steps it already finished when you
  resume. A step already running finishes first; the jobs page says which and how long it usually takes (a
  video step can take several minutes). Plans and tests for a new path are never paused.
- New paths can be Shorter, Standard or Deep. A path from a goal is now planned much bigger (40 to 70 lessons
  for Standard, 80 to 120 for Deep); lessons are still written only as you get close to them, so a longer path
  costs nothing until then.
- A course from your own material is planned as big as the material: one recorded lecture is a lesson or two,
  a book dozens of lessons, with Shorter or Deep covering less or more of it.
- "Why are you learning this?" takes several answers.
- The jobs page shows each waiting job's place in line and the rule behind the order, and a queued lesson on
  the path shows its place too. A lesson you ask for now goes ahead of the lessons written ahead of you.
- "Save app shortcut" is in the menu on every browser: where the browser has no install button (Firefox,
  Safari), it shows the steps for that browser.
- After an update, the page reloads by itself and then says which version is running, instead of a reload
  button that seemed to do nothing.
- Signing in to Claude Code or Codex: the setup no longer says "Done" before you are signed in, and when the
  sign-in state is unclear it shows the sign-in button and checks again by itself.
- The container setup explains how to start Yuo again after a restart of the computer, and the update
  commands are shown in Settings.
- A path's own state (its level check, plan choices, preview, next steps) is no longer written into packages
  you share.

## [1.1.0] - 2026-11-19

- A new Home shows, at a glance, what to do next and how it goes across all your paths: the lesson to continue,
  what waits today (reviews due, skills fading, a lesson waiting for your decision, files being transcribed, a
  suggestion for your material, an exam coming up), your mastery and how it moved this week, your streak and
  XP, and one observation from your own answers. The list of paths moved to Paths.
- Paths can be renamed, have their goal changed, be archived (out of sight, brought back at any time) or be
  deleted with everything in them, from the menu on each path in Paths.
- Reading pages from their images shows how many pages are done of how many, and reading and planning your
  material shows a progress bar with the file or course it is working on.
- A path from your own material starts from the files alone: add everything for every course at once, and Yuo
  suggests the path's name and how the files split into courses, with a note on why. Change it in your own
  words, choose how closely each course keeps to its files, and take it. Your files are dropped right on the
  new-path form, and nothing is made until you add them.
- Long recordings no longer run out of memory while they are transcribed: the speech is transcribed a few
  minutes at a time, with flat memory whatever the length, and when the transcription is still stopped it goes
  on from where it was instead of starting over. A file that failed can be tried again without uploading it.
- A lecture video in MP4 or MOV is uploaded as its sound only: the audio track is taken out in the browser,
  unchanged, so a 70 MB video sends a few MB. The video was never kept anyway.
- PDF pages whose formulas or symbols are missing from the text (drawn as shapes, or left as gaps) are
  flagged, and reading them from their images is recommended for them: what the model reads replaces the
  page's text, formulas in LaTeX. Up to 300 pages per file, those missing the most first.
- Maths is written in LaTeX and shown as formulas everywhere: inside lesson text (not only in formula blocks),
  in practice, test, review and level check questions, their options, hints, solutions and feedback, and in
  the tutor's replies. What a learner types as an answer stays plain.
- A lesson that keeps failing its review can be accepted with feedback: its best draft is published with the
  reviewer's notes on what may be wrong shown at the top, and it can be written again from there.
- **See the plan before it is built**: a new path shows its branches, skills and lessons first. Say in your
  own words what is missing, wrong or should go deeper, and Yuo changes the plan; go back to an earlier
  version, or build it when it fits.
- **Learn from your own material**: start a path from your books, slides, notes and recordings instead of
  a goal. One path per subject (for example "Mechanical Engineering"), one branch per course, exam, book or
  topic. Add your files (PDF, PowerPoint, Word, text, audio and video); Yuo reads them on your computer
  first, and transcribes recordings there too. Then it plans each course on its material, finds where
  courses build on each other, and shows the plan per course for your feedback. For each course choose how
  closely to follow the material: only your material, your material first, or your material and beyond.
  Lessons are written from the matching pages and link back to them, and the tutor sees those pages too.
  Practice, test and review questions are written from the same pages; with "only my material" each
  question must be answerable from them, and the automatic answer check uses only those pages.
- Each course of your own material shows what it covers: a bar per file, with the parts that are taught (one
  click opens the lesson), left out (and why) or not used yet.
- Past exams and exercise sheets you add are never turned into lessons: their matching tasks show the style and
  difficulty for that course's questions. A built course offers a mock exam: two questions per skill, no hints
  or feedback until the end, the skills to go back to, and no change to your progress.
- PDF pages that are mostly formulas or figures can be read from their images: one click on the file, and
  the generation model writes out the formulas (LaTeX) and describes the figures.
- The tutor also searches all of your material for your question, past exams and exercises included, and
  shows where each passage comes from.
- Recorded lectures are matched to the course's slides: a lesson written from a part of a lecture also points
  to the slides shown during it.
- A file can be removed from a course that is already built: the lessons written from it are written again
  without it, and stay readable until then.
- Uploads resume after a dropped connection.
- **Recordings no longer hold up the plan**: they are transcribed as soon as they are uploaded, books and
  slides are read first, and a course is planned once its documents are read. Each recording then joins the
  plan when it is ready, and the plan says what changed. After the path is built, add files to a course at
  any time: their passages go into the lessons not written yet, and Yuo suggests rewriting the lessons they
  touch and adding new skills, for a yes or a "not now". Settings > Transcribing recordings: "Faster" uses
  a smaller speech model, about three times quicker.

## [1.0.1] - 2026-11-16

- **A second copy on the same machine** no longer touches the first: `YUO_PROJECT` and `YUO_HOST_PORT` in
  `.env` give it its own containers, data volume and port. Existing installs keep their names.
- **Setup with an AI assistant**: the assistant hands over Yuo's address and setup code as soon as Yuo
  answers, as a link that works on the device the person is using; a new SSH tunnel route to try Yuo on a
  server without opening anything; consistent memory, disk and volume figures; the Remotion licence note
  for work computers.
- The answers file an assistant saves for Yuo's setup is readable by Yuo only.

## [1.0.0] - 2026-11-16

The first public release.

- **Learning paths**: describe what you want to learn and why; Yuo checks your level with a few questions and
  plans a skill tree of short lessons, shown as a graph you can pan, zoom and explore, or as a list. "What
  next?" keeps a path going once a branch is done.
- **Lessons**: readings written for you and checked by a second model before you see them, with cited
  sources; narrated videos made for each lesson, reviewed and repaired before they are published, with
  captions as a separate track; practice in seven exercise types; notes on any lesson; lessons on request.
- **Remembering**: skill tests that unlock what comes next, remedial lessons when a test shows a gap, spaced
  review (FSRS) with a Review hub per path, memory per skill and objective, flashcards, mastery, XP and streaks.
- **Tutor**: always one tap away, aware of what is on screen, never gives away a test answer, remembers what
  you allow it to, and can suggest when to review.
- **Your choice of AI**: your Claude or ChatGPT subscription, an OpenRouter key, a key from Anthropic, OpenAI,
  Google, Mistral, DeepSeek, xAI or Qwen, or a model on your own machine. Every choice comes with a cost
  estimate for a typical path, or how much of your plan it uses.
- **Your data stays with you**: no account with Yuo's makers, no telemetry; learning data leaves your machine
  only for the AI model you choose. Erase a conversation, a path's data or the video history at any time.
- **Sharing**: path packages to share a path ready to study, as structure and texts, or in parts, with personal
  content left out unless you choose it; standard exports (CSV, Anki, Moodle XML, readings, videos with
  subtitles, BibTeX, CSL JSON).
- **Every device**: the server version (Docker) with passkeys, a password and recovery codes, reachable through
  Tailscale, Caddy or your own proxy, installable as an app on phones; daily checked backups and restore; an
  offline outbox that syncs when you are back.
- **Desktop app** for Windows, macOS (Apple silicon) and Linux: double-click to start, signed in on this
  computer, updates that roll back by themselves if a new version does not start. Text only: no videos.
- **Setup with an AI assistant**: paste one prompt into Claude Code, Codex or a similar assistant; it follows
  [SETUP.md](SETUP.md), installs Docker if needed, and drafts your first path for Yuo's setup to start from.
- English, Italian, Spanish, Portuguese and German; light and dark themes.
