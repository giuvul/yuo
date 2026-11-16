# Security policy

## Supported versions

The latest release gets security fixes. Update to it before reporting: the desktop app updates itself, and the
server version updates by setting the new version in `YUO_IMAGE` and running `docker compose pull && docker
compose up -d`.

## Reporting a vulnerability

Please report it privately through GitHub's
[Report a vulnerability](https://github.com/giuvul/yuo/security/advisories/new) form. Do not open a public
issue. Include the version, how you run Yuo, how to reproduce the problem and the impact you expect. You will
get a first answer within 7 days, and credit in the release notes if you want it.

## How Yuo protects you

- **Your data stays on your machine.** There is no telemetry, analytics or service run by Yuo's makers.
  Learning data leaves the install only for the AI model the learner chose; video narration runs locally.
  Every request to a remote model is recorded on the install. Updates, model prices and downloads carry no
  learner data.
- **Model-written code** (the scenes of a video) runs only in a sandbox without network access, never in the
  server.
- **Sign-in** on the server version uses passkeys, a password as the fallback and recovery codes, with Host
  header and CSRF protection; the desktop app listens only on this computer.
- **Keys** are kept in the system keychain or in a file encrypted with a key you hold, and are never logged or
  sent back to the browser.
- **Imported path packages** are treated as untrusted input: size limits, no executable content.

More in [docs/architecture.md](docs/architecture.md#8-security).
