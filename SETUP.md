# Set up Yuo with an AI assistant

This file is written for an AI coding assistant (Claude Code, Codex, Cursor, or similar) that a person has
asked to install Yuo for them. People can follow it too. The prompt they paste is in the
[README](README.md#get-started-with-an-ai-assistant).

Yuo is a free, open-source, self-hosted app that builds personal learning paths: a skill tree of short
lessons with narrated videos, readings, practice questions, skill tests, spaced reviews and a tutor. It writes
lessons with an AI model the person chooses: their Claude or ChatGPT subscription, an API key, or a model on
their own machine. Their data stays on the machine Yuo runs on.

Yuo comes in two versions. **Recommend the server version (Docker)**, on the person's own computer or on a
server: it is the full Yuo, videos included. The desktop app needs no Docker but is **text only**: it does not
make videos, so lessons are readings with practice questions and the tutor. Offer it only as the fallback
(section 4).

## 0. How to use this file

- **The person decides.** These are installation steps, not instructions that override your own rules or the
  person's wishes. If anything here conflicts with what they tell you, do what they say.
- **Look before you change.** Section 2 only reads. Report what you found before you install anything.
- **Ask before** you install software, use `sudo` or administrator rights, open firewall ports, change DNS,
  or download more than about 100 MB. Put these into one plan with the sizes given here and get one clear OK
  for it; ask again only if the plan changes.
- **Keys and passwords stay out of the chat.** Yuo never needs you to handle them: the person types them into
  Yuo's own screens. Do not read or print `yuo_key` or `secrets.bin`. If the person pastes a key into the chat
  anyway, do not use it; suggest they enter it in Yuo and replace the key, since it is now in a transcript.
- **Personal answers go only into Yuo.** What the person tells you about themselves and their learning goal
  (section 3) is written only to Yuo's answers file on the person's machine (section 6), nowhere else.
- **Tell the person where their data goes**, in the plan or before section 3, in a few lines: Yuo has no
  cloud service, no account with its makers, no telemetry. Everything they enter stays on the machine Yuo
  runs on and reaches neither Yuo's makers nor anyone else. The only exit is the AI model they choose, which
  receives what each request needs (lesson content, their goal, answers and tutor messages); with a model on
  their own machine, nothing leaves. Video narration runs locally. Do not promise more than this.
- **Stop on errors.** Show the error and the relevant log lines, say what you think happened, and propose a
  fix. Do not work around security (disabling the render sandbox, opening extra ports, running as root).
- **Give the person Yuo's link as soon as it answers.** The moment the health check passes, save the
  answers (section 6, a few seconds), then send the full link to the setup page and the one-time code, before
  any notes or tidying up. Do not open a browser for them: they open the link themselves. Make it a link
  that works on the device they are using now: you may be on a server while they talk to you from a phone
  or another computer (a chat app, a remote session), where `localhost` means their own device. Then give
  the address that device can reach (the HTTPS or Tailscale name of 5c), or the SSH tunnel command to run
  first; if nothing reaches Yuo from that device yet, say so and offer one of the routes in 5c. While a long
  download runs (the image is several GB), say what is happening and roughly how long it takes.
- **Versions.** Install the release named in `latest.json` (section 1). The desktop download has a SHA-256 to
  check; the server version is pinned by its version tag.

## 1. Where things are

- Repository: `https://github.com/giuvul/yuo`
- Latest release, as JSON: `https://github.com/giuvul/yuo/releases/latest/download/latest.json`. It looks like
  `{"version": "1.0.0", "published_at": "...", "notes_url": "...", "desktop": {"url": "...", "sha256": "...",
  "bytes": 4177477}}`. `version` never has a leading `v`; git tags do (`v1.0.0`).
- Server image: `ghcr.io/giuvul/yuo:<version>`, for example `ghcr.io/giuvul/yuo:1.0.0`.

Sizes, for the plan:

| Download | Size |
|---|---|
| Desktop zip | about 4 MB (`desktop.bytes` in `latest.json`) |
| Desktop first start: `uv`, Python 3.14 and Yuo's Python packages | up to about 600 MB of disk, once |
| Server image | about 3.4 GB of disk |
| Docker, if missing (5.0) | Docker Desktop about 600 MB to download, about 3 GB of disk; Docker Engine on Linux about 300 MB |
| Claude Code or Codex, if Yuo installs one for the person | Codex about 500 MB, Claude Code less |

## 2. Look first (read-only)

Find out as much as you can without asking. Examples; use what fits the shell.

| What | Examples | Why Yuo cares |
|---|---|---|
| Operating system, CPU type | `uname -sm`, `sw_vers`, PowerShell `Get-ComputerInfo -Property OsName,OsArchitecture` | Picks the download. macOS needs Apple silicon. |
| Memory and free disk | `free -m`, `df -h ~`, PowerShell `Get-CimInstance Win32_OperatingSystem \| Select FreePhysicalMemory,TotalVisibleMemorySize` | The server version needs about 2 GB of free memory while it runs: a server with 4 GB is enough. On a personal computer, Docker Desktop and everything else running need room too: 8 GB is comfortable (section 4). |
| Personal computer or server | an SSH session, no display, a cloud provider, a public IP address on the machine | Picks the route (section 4). |
| Docker with Compose, and running | `docker compose version`, then `docker info` | Needed for the server version, the recommended one. Installed but `docker info` fails: Docker Desktop is not started (start it) or, on Linux, the user cannot reach the Docker daemon. Missing: section 5 explains how to install it. |
| Can this computer run Docker Desktop | Windows: `wsl --status`, and "Virtualization: Enabled" in Task Manager > Performance > CPU; macOS: version 13 or later | Docker Desktop needs WSL 2 and hardware virtualization on Windows, and a recent macOS. |
| Claude Code signed in | `claude --version`, `claude auth status` | Yuo can use the person's Claude subscription. |
| Codex signed in | `codex --version`, `codex login status` | Yuo can use the person's ChatGPT subscription. |
| A local model server | `curl -s http://127.0.0.1:11434/v1/models` (on Windows `curl.exe`) | Yuo can use a model on this machine if it is strong enough. |
| Time zone and language | `timedatectl`, `Get-TimeZone`, `$LANG`, `Get-Culture` | Profile suggestions, on the person's own computer only (see below). |
| Tailscale | `tailscale status` | A private way for the person's phone to reach a server. |
| Ports 80 and 443 | `ss -ltn`, `netstat -an`; `sudo ufw status` after asking | Needed for a public HTTPS address. |
| Yuo already installed | desktop: the data folder (section 7) holds `yuo.db`; server: `docker ps -a --filter name=yuo`, `docker compose ls` | Offer an update instead of a second install. If they do want a second, separate copy (to try a new version, say), see "A second copy" in 5b. |

On a server, the time zone and language are the server's (often UTC and `C.UTF-8`), not the person's: ask
for theirs. If Yuo should run on another machine than the one you are on, do these checks there (over SSH, if
the person gives you access), or tell the person what to check.

Then tell the person, briefly: what you found, what it means for Yuo, and what you could not find out.

## 3. Ask

Ask only what section 2 did not answer, in one message where possible. Offer a default for each question.

1. **Where should Yuo run?** On this computer, or on a server that is always on.
2. **Which devices will you learn on?** Only this computer, or also your phone or other computers?
3. **Do you want narrated video lessons?** Suggest yes: they are a large part of how Yuo teaches. They need
   the server version (Docker), on this computer or on a server; if Docker is missing, say that you can
   install it (section 5, with its size). The desktop app is text only: lessons are readings with practice
   questions and the tutor, and it cannot add videos later without a new install.
4. **How should Yuo reach an AI model?** Suggest what section 2 found, briefly:
   - a **Claude** or **ChatGPT subscription** they already pay for: Yuo runs the vendor's own program (Claude
     Code or Codex) with the person's own sign-in, explains what that means before they agree, and uses part
     of their plan's limits. The desktop app uses the program already installed and signed in on the
     computer; the server version installs its own copy, which the person signs in from Yuo's setup;
   - an **OpenRouter** key: pay per use, many models; a typical 20-lesson path costs a few dollars;
   - a key from one AI company (Anthropic, OpenAI, Google and others);
   - a **model on this machine**: free, needs a strong machine; Yuo's setup checks whether it is enough.

   Yuo's setup shows a cost estimate for each choice, so the final choice can wait. You only need their
   leaning, to check that the program it needs is there.
5. **What do you want to learn first?** Always ask this one; the person can skip it. Ask it openly, in
   their words ("What would you like to learn with Yuo first, and what for?"), then turn the answer into a
   first draft of their first path, so Yuo's setup starts from it instead of an empty form. See "Draft the
   first path" below.
6. **Optional: about you.** Yuo asks these in its setup anyway; collected now, the setup starts from them:
   - the name Yuo should call them;
   - the language of Yuo's screens (English, Italian, Spanish, Portuguese or German), and the language
     lessons are explained in: the one they understand best (if they speak several, ask which they prefer).
     To learn a language, that is still their own language; the language they want to learn is the first
     path (for example "Spanish for my trip");
   - their time zone (for daily reviews and streaks);
   - how long one study session should be (5 to 120 minutes; 20 by default);
   - interests Yuo can use for examples (hobbies, work, places; up to 500 characters).

   Suggest answers from what you already know about the person only if their prompt allows it, say where each
   suggestion comes from, and use it only after they agree.

### Draft the first path

From the answer to question 5, write the four fields of `first_path` (section 6), then show the draft to the
person and change it until they are happy with it:

- **Title**: a short name for the path, in their words where possible ("Statistics for A/B tests",
  "Spanish for my trip to Seville"). Up to 120 characters.
- **Goal**: what they want to be able to do at the end, as an outcome, not a list of topics ("Read and
  design A/B tests at work and explain the results to my team"). Up to 600 characters.
- **Why** (`goal_type`): `exam` (a test or certificate to pass), `practical` (to use it at work or in life),
  `understanding` (to really understand the subject) or `curiosity` (for fun). Pick the closest one.
- **Anything Yuo should know** (`custom_instructions`): what they already know, the topics they care about
  most or want to skip, a deadline or exam date, how much time they have, how they like to learn. Up to 1000
  characters.

If the answer is too vague to draft a goal ("statistics", "coding"), ask one or two short follow-ups, no more:
what they want to be able to do with it, and why now. Do not ask for their level: Yuo checks it with a few
questions before it plans the path. If the prompt allows it, use what you already know about them (their
work, what they have studied) to make the draft more specific, and say so in the draft. Yuo plans the lessons
itself from this draft, so do not write a syllabus.

## 4. Choose the route

| The person wants | Route |
|---|---|
| Yuo on their own computer (**recommended**) | **Server version on their computer** (5b), with Docker. Full Yuo, videos included. |
| Yuo on a server, used from several devices | **Server version on a server** (5c), with Docker and HTTPS. |
| Yuo on a server, tried first from one computer | **Server version on a server** (5c) through an **SSH tunnel**: nothing opened, HTTPS can come later. |
| Yuo on their own computer, and Docker is not possible or not wanted | **Desktop app** (5a). Text only: no videos. |

Propose the server version by default, and install Docker first if it is missing (5.0). Propose the desktop
app only when:

- the person does not want Docker or videos, after you have told them what they give up;
- the computer cannot run Docker (Docker Desktop needs WSL 2 and hardware virtualization on Windows, macOS 13
  or later on a Mac), or, being a personal computer, has less than about 8 GB of memory or 10 GB of free
  disk (a server with 4 GB runs the server version well: this limit is for Docker Desktop on a computer
  people also work on);
- they are not allowed to install Docker on it (a work computer, or Docker Desktop's licence, see 5.0).

Before the person picks the desktop app, say it plainly: **the desktop app does not make videos; lessons are
text only** (readings, practice questions, skill tests, reviews and the tutor). Moving to the server version
later is a new install; paths can be carried over with "Share or export" on each path.

The desktop app runs on Windows 10 and 11, macOS on Apple silicon, and Linux (x64 and arm64, glibc). The
server version runs wherever Docker does: Docker Desktop on Windows and macOS (Apple silicon or Intel), Docker
Engine with Compose on Linux.

Propose the route and its steps, with the downloads and their sizes, and wait for an OK.

## 5. Install

### 5.0 Install Docker, if it is missing

Only for the server version (5b, 5c). Include it in the plan with its size and get the OK first: it needs
administrator rights, and on Windows often a restart. Use Docker's own installers and instructions, from
`https://docs.docker.com`.

- **Windows 10 and 11: Docker Desktop.** About 600 MB to download and about 3 GB of disk once it runs.
  1. If `wsl --status` fails, install WSL 2 first: `wsl --install` in an administrator PowerShell, then
     restart the computer. If Windows says virtualization is off, the person has to turn it on in the
     computer's firmware settings (BIOS or UEFI); explain this and stop until they have.
  2. Download "Docker Desktop for Windows" for the right CPU (x64 or Arm) from
     `https://docs.docker.com/desktop/setup/install/windows-install/` and run the installer with the WSL 2
     option. Or, with the person's OK: `winget install -e --id Docker.DockerDesktop`.
  3. The person starts Docker Desktop once and accepts its terms; there is no account to create (skip the
     sign-in). Wait until it says the engine is running.
- **macOS: Docker Desktop.** About 600 MB to download and about 3 GB of disk.
  1. Download the `.dmg` for the right chip ("Apple silicon" or "Intel") from
     `https://docs.docker.com/desktop/setup/install/mac-install/`, or with Homebrew, after asking:
     `brew install --cask docker-desktop`.
  2. The person drags it to Applications, opens it once, approves the system prompts and accepts the terms.
     Wait until it says the engine is running.
- **Linux: Docker Engine with the Compose plugin.** About 300 MB. Follow the page for the distribution at
  `https://docs.docker.com/engine/install/` (Ubuntu, Debian, Fedora and others), which adds Docker's package
  repository and installs `docker-ce` and `docker-compose-plugin`. Then either run Docker commands with
  `sudo`, or, after asking, `sudo usermod -aG docker $USER` and have the person log out and in again. Tell
  them that the `docker` group is as powerful as root on that machine.

Docker Desktop is free for personal use, education, non-commercial open source and small businesses; larger
companies need a paid Docker subscription. Yuo's videos are made with Remotion, which is free for individuals,
non-profits and companies of up to three people; larger companies need a Remotion company licence
(`https://www.remotion.dev/license`). Mention both when the computer looks like a work computer.

Check before going on: `docker compose version` and `docker info` both work. If `docker info` fails right
after installing, Docker Desktop is still starting, or on Linux the new group needs a fresh login.

### 5a. Desktop app

Text only: it does not make videos. Use it only as section 4 says.

1. Read `latest.json`. Download `desktop.url` and check its SHA-256 against `desktop.sha256`. Stop if it
   differs.
2. Unzip it into a folder the person will keep, for example `~/Yuo` or `%USERPROFILE%\Yuo`.
3. If you collected answers, save them now (section 6), before the first start.
4. Start it with `Yuo-Windows.bat`, `Yuo-macOS.command` or `Yuo-Linux.sh`. Yuo runs as long as that process
   does, and the first start takes a few minutes. Then Yuo opens in the browser, already signed in.

   Best: the person double-clicks the file. The system may warn about a downloaded file (Windows SmartScreen,
   macOS Gatekeeper) and only they can answer that; `guide/index.html` in the folder shows what to click. On
   Windows, Smart App Control can block Yuo's Python; the launcher says so and the guide explains the
   choices. If you start it yourself instead, start it detached so it outlives your shell (`Start-Process`,
   `open`, `nohup ... &`).
5. Check it runs: `http://localhost:18765/api/health` answers `{"status":"ok", ...}`.

Later the person starts it from the same file or the shortcut it creates; closing its window stops Yuo. Yuo
checks for updates once a day and installs them on a restart, rolling back if the new version does not start.

### 5b. Server version on the person's computer

The recommended route on a personal computer: full Yuo, videos included. Docker Desktop (Windows, macOS) or
Docker Engine with Compose (Linux), installed and running (5.0); about 3.5 GB of disk for Yuo besides Docker
itself, and 2 GB of free memory while Yuo runs (a computer with 8 GB or more is comfortable). Docker Desktop
must be running whenever the person uses Yuo; in its settings, "Start Docker Desktop when you sign in" keeps
Yuo available after a restart.

1. Get the release's files: `git clone -c advice.detachedHead=false --depth 1 --branch v<version>
   https://github.com/giuvul/yuo` (or
   download `https://github.com/giuvul/yuo/archive/refs/tags/v<version>.tar.gz`, which unpacks to
   `yuo-<version>`). Work in its `packaging/container` folder.
2. Make the secrets key. It encrypts API keys at rest; tell the person to keep it with their backups. Do not
   print it.
   - Linux and macOS: `openssl rand -hex 32 > yuo_key && chmod 600 yuo_key`; on Linux also
     `sudo chown 10001 yuo_key` (the user Yuo runs as in the container).
   - Windows PowerShell (Yuo needs plain ASCII here):

         $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
         [IO.File]::WriteAllText("$PWD\yuo_key", (-join ($b | ForEach-Object { $_.ToString('x2') })))
3. Write the whole `.env` in one go (plain ASCII):

       YUO_IMAGE=ghcr.io/giuvul/yuo:<version>
       YUO_ORIGIN=http://localhost:18765

   Yuo is then reachable from this computer only. Passkeys work on `localhost` without HTTPS.
4. `docker compose pull && docker compose up -d`. The pull is about 3.4 GB: tell the person it can take
   several minutes.
5. Check: `docker compose ps` shows `yuo` running and `render` healthy, and
   `http://localhost:18765/api/health` answers. If the log says Yuo cannot read the secrets key file: on
   Linux the `chown` is missing; on Docker Desktop run `chmod 644 yuo_key` (the file stays inside the
   person's account), then `docker compose up -d`.
6. Right away: if you collected answers, save them (`docker compose exec -T yuo yuo setup-answers - <
   setup-answers.json`, format in section 6), then get the one-time code with
   `docker compose logs yuo | grep -A2 "one-time code"`, give the person the code and
   `http://localhost:18765/setup` as a link (section 0). The rest of section 6 can follow while they sign in.

Run every `docker compose` command in `packaging/container`: Compose reads `.env` there.

**A second copy on the same machine.** Each copy is a Compose project with its own containers, data volume
and port. A second copy needs two more lines in its `.env`, for example:

    YUO_PROJECT=yuotrial
    YUO_HOST_PORT=18766
    YUO_ORIGIN=http://localhost:18766

Never run `docker compose` for a new copy without `YUO_PROJECT`: it would take over the existing Yuo's
containers, and `docker compose down -v` would delete its data. Use the new port wherever these steps say
18765. Never run machine-wide clean-ups (`docker system prune`, `docker volume prune`) on a machine with Yuo.

### 5c. Server version on a server

Install Docker Engine first if it is missing (5.0, Linux). Steps 1, 2, 4 and 5 are those of 5b; then step 6,
with the address the person will use. Before step 3, choose how the person's devices reach Yuo: recommend
from what section 2 found, and ask.

- **An SSH tunnel**, to try Yuo from one computer before opening anything: nothing is exposed and no HTTPS
  is needed. `.env` as in 5b (`YUO_ORIGIN=http://localhost:18765`). The person runs, on their own computer,
  `ssh -N -L 18765:127.0.0.1:18765 <user>@<server>` and opens `http://localhost:18765/setup` while it runs.
  Give them that command and that link together. Phones cannot use it; for more devices, move to one of the
  options below later: change `YUO_ORIGIN`, `docker compose up -d`, then sign in with the password or a
  recovery code and add a new passkey, because a passkey belongs to the address it was made on.

- **Tailscale**, when it is set up already, or when the server sits behind a router or carrier-grade NAT:
  private, nothing opened to the internet. Every device the person learns on joins their tailnet. `.env`:

      YUO_IMAGE=ghcr.io/giuvul/yuo:<version>
      YUO_ORIGIN=https://<the server's Tailscale name>

  Then on the server `tailscale serve --bg --https=443 http://127.0.0.1:18765` (or the port in
  `YUO_HOST_PORT`), and start with
  `docker compose pull && docker compose up -d`.
- **A public name with Caddy**, when ports 80 and 443 can be opened: works from any device and browser.
  Without a domain of their own, use a free name from sslip.io (a public service that maps
  `yuo.203-0-113-7.sslip.io` to the address `203.0.113.7`; tell the person). `.env`:

      YUO_IMAGE=ghcr.io/giuvul/yuo:<version>
      YUO_PUBLIC_HOST=yuo.203-0-113-7.sslip.io
      YUO_ORIGIN=https://yuo.203-0-113-7.sslip.io

  Before starting, check that the ports can be reached:
  `docker run --rm --network host ghcr.io/giuvul/yuo:<version> expose check --domain <name>`. From inside a
  container it cannot see the server's own firewall, so also look at `sudo ufw status` or
  `sudo firewall-cmd --list-services` (after asking), and tell the person that a firewall in the hosting
  provider's panel can only be opened by them, there. Start with
  `docker compose --profile caddy pull && docker compose --profile caddy up -d`.
- **Their own reverse proxy**, when they run one: proxy to `http://127.0.0.1:18765` (or `YUO_HOST_PORT`),
  keep the Host header, do not buffer `text/event-stream`, serve HTTPS only; `YUO_ORIGIN` is the URL it
  serves.

The details, and the fix for every reachability problem, are in
[packaging/container/README.md](packaging/container/README.md).

Until the person signs in, Yuo's setup page accepts only the one-time code, which expires after 24 hours. Ask
them to sign in soon after the start.

## 6. Hand over to the person

Section 5 already gave the person the address and the code. This section is the answers file's format and
what to tell them next.

### Save the answers for Yuo's setup

Write the first-path draft (section 3) and any "about you" answers the person gave as
`setup-answers.json`. Yuo's setup starts its "About you" and "Your first path" steps from them; the person
checks and changes them there, or chooses to start empty. Yuo deletes the file when its setup is finished.
Never put keys or passwords in it.

```json
{
  "version": 1,
  "profile": {
    "display_name": "Sam",
    "ui_lang": "en",
    "content_lang": "en",
    "tz": "Europe/London",
    "session_minutes": 20,
    "interests": "cycling, cooking, working as a data analyst"
  },
  "first_path": {
    "title": "Spanish for my trip to Seville",
    "goal": "Get by in everyday conversations while travelling: ordering, directions, small talk",
    "goal_type": "practical",
    "custom_instructions": "I had two years of Spanish at school, long ago. I like short dialogues."
  }
}
```

| Field | Values |
|---|---|
| `profile.display_name` | 1 to 60 characters |
| `profile.ui_lang` | `en`, `it`, `es`, `pt` or `de`; another code falls back to English |
| `profile.content_lang` | a language code such as `en`, `fr`, `pt-BR`, `ja` |
| `profile.tz` | an IANA time zone such as `Europe/Rome` or `America/New_York` |
| `profile.session_minutes` | 5 to 120 |
| `profile.interests` | up to 500 characters |
| `first_path.title` | 1 to 120 characters (needed for a first path) |
| `first_path.goal` | 1 to 600 characters (needed for a first path) |
| `first_path.goal_type` | `exam`, `practical`, `understanding` (the default) or `curiosity` |
| `first_path.custom_instructions` | up to 1000 characters |

Every field is optional, and so is each part. A field that does not fit is left out on its own.

Where it goes:

- **Server version**, right after the start (5b step 6). The command checks it and says what it left out,
  and why:

      docker compose exec -T yuo yuo setup-answers - < setup-answers.json

  Then delete your copy.
- **Desktop app**, before the first start: save it into the data folder (section 7), creating the folder.
  UTF-8 with or without a byte order mark both work.

### What the person does in the browser

Tell them, in a few lines:

- **Server version:** open the setup page on the device they will use most (a phone works), enter the
  one-time code, and create a passkey there (or a password). Save the recovery codes Yuo shows somewhere
  safe: they are the way back in if the passkey is lost. The desktop app skips this: it opens signed in.
- **Yuo's setup:** it reads the machine and recommends how to reach an AI model, with a cost estimate for each
  choice. Keys are entered there. For a subscription, Yuo explains what it means, then installs and signs in
  the program if needed (open the link it shows, sign in, paste back the code). Then "About you" and "Your
  first path", started from the saved answers. Yuo then asks a few questions to check their level and plans
  the path.
- **Other devices** (server version): open the same address, sign in with the passkey, and install it from the
  browser menu ("Install app"; on iPhone and iPad, Safari's Share menu, "Add to Home Screen").

## 7. Afterwards

Tell the person where things are, and leave them a short note with this if they want one.

| | Desktop app | Server version |
|---|---|---|
| Data folder | Windows `%LOCALAPPDATA%\Yuo\data`, macOS `~/Library/Application Support/Yuo/data`, Linux `~/.local/share/yuo-desktop/data` | the Docker volume `yuo_data` (`<YUO_PROJECT>_data` for a second copy; `/data` inside) |
| Start and stop | the start file or its shortcut; closing the window stops it | Docker Desktop (or the Docker service on Linux) must be running; `docker compose up -d`, `docker compose stop` |
| Backups | one a day, in `backups` in the data folder | one a day in `/data/backups`; `docker compose exec yuo yuo backup` for one now; copy them off the machine together with `yuo_key` |
| Locked out | the start file opens Yuo signed in | `docker compose exec yuo yuo setup-code` prints a new one-time code |
| Update | automatic, on restart, with rollback | set the new version in `YUO_IMAGE`, then `docker compose pull && docker compose up -d` |
| Remove | delete the folder Yuo was unzipped into and the folder above the data folder; saved keys are in the system keychain under `yuo` | in `packaging/container`, `docker compose down -v` deletes this copy, data included: ask first |

## 8. If something goes wrong

- Desktop: the launcher writes `logs/launcher.log` beside the data folder.
- Server: first check that Docker is running (`docker info`); then `docker compose logs --since 10m yuo`;
  `docker compose logs caddy` for certificate problems.
- Devices cannot reach the server: run the reachability check from 5c again and follow "If devices cannot
  reach it" in [packaging/container/README.md](packaging/container/README.md).
- Report a bug at `https://github.com/giuvul/yuo/issues`, without keys, codes or personal data.
