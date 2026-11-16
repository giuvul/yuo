# Yuo on a server

One server, every device: the app runs in a container, other devices reach it over HTTPS, and everyone signs
in (passkey, password or a recovery code). A second container with no network renders the videos.

Needs Docker with Compose, about 3 GB of disk for the image, and 2 GB of free memory (4 GB machine or more).

## Install

Run these in this folder (`packaging/container`).

1. **Choose the image**: the release's, by its version (`latest.json` in the release has it, without the `v`):

       echo "YUO_IMAGE=ghcr.io/giuvul/yuo:1.0.0" > .env

   (To build your own instead: `docker build -f Dockerfile -t yuo:dev ../..` and leave `YUO_IMAGE` out.)

2. **Make the secrets key** (encrypts API keys at rest; keep it with your backups):

       openssl rand -hex 32 > yuo_key && chmod 600 yuo_key && sudo chown 10001 yuo_key

   (10001 is the user Yuo runs as in the container; Compose mounts the file with these permissions.)

3. **Choose how devices reach it** and write `.env`:

   - **Tailscale** (private, works behind any router): install Tailscale on the server and sign in, then

         tailscale serve --bg --https=443 http://127.0.0.1:18765
         echo "YUO_ORIGIN=https://$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')" >> .env

     Every device that should use Yuo joins the same tailnet.
   - **A public name with Caddy** (ports 80 and 443 free on the server): use your domain, or a free sslip.io
     name made from the server's public IP address (`203.0.113.7` becomes `yuo.203-0-113-7.sslip.io`):

         echo "YUO_PUBLIC_HOST=yuo.203-0-113-7.sslip.io" >> .env
         echo "YUO_ORIGIN=https://yuo.203-0-113-7.sslip.io" >> .env

     and start with `--profile caddy` below. Ports 80 and 443 must be open from the internet: check them
     first, and again after the start if a device cannot connect (see
     [If devices cannot reach it](#if-devices-cannot-reach-it)):

         docker run --rm --network host ghcr.io/giuvul/yuo:1.0.0 expose check --domain yuo.203-0-113-7.sslip.io
   - **Your own reverse proxy**: proxy to `http://127.0.0.1:18765`, keep the Host header, don't buffer
     `text/event-stream`, serve HTTPS only; set `YUO_ORIGIN` to the URL it serves.

4. **Start**:

       docker compose pull && docker compose up -d     # with Caddy: docker compose --profile caddy pull && docker compose --profile caddy up -d

5. **Sign in the first time**: the server prints a one-time setup code.

       docker compose logs yuo | grep -A2 "one-time code"

   Open `YUO_ORIGIN/setup`, enter the code, add a passkey (or a password), and save the recovery codes.

6. **Second device**: open `YUO_ORIGIN` and sign in with your passkey (synced passkeys work on your other
   devices; otherwise use the password, then add a passkey on that device). Install it from the browser menu
   ("Install app" / "Add to Home Screen").

## If devices cannot reach it

`yuo expose check --domain NAME` (or `--ip ADDRESS`) looks at what the server can see: whether the name
points at it, whether the server holds its public address itself or sits behind a router, whether ufw or
firewalld lets ports 80 and 443 in (only outside Docker, as root: the container cannot see the server's
firewall), and whether anything answers. It prints every fix that can apply, the likely ones first. In short:

- **The name does not point at the server**: add an A record (AAAA for IPv6) with the server's public
  address at your DNS provider. sslip.io names need nothing.
- **A firewall on the server**: ufw: `sudo ufw allow 80/tcp && sudo ufw allow 443/tcp`. firewalld:
  `sudo firewall-cmd --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload`.
  Windows (PowerShell as administrator): `New-NetFirewallRule -DisplayName "Yuo web" -Direction Inbound
  -Protocol TCP -LocalPort 80,443 -Action Allow`. macOS: System Settings > Network > Firewall > Options.
- **A firewall in front of the server** (rented servers): allow inbound TCP 80 and 443 in the provider's
  panel (security group, cloud firewall). The server cannot see this one, so the check cannot either.
- **A router in front of the server** (home or office): forward TCP 80 and 443 to the server's address on
  that network, and give the server a fixed address there.
- **Carrier-grade NAT** (the router's WAN address is 100.64.x.x to 100.127.x.x, or differs from the address
  websites show for you): no port can be opened. Use Tailscale instead (above), or ask the provider for a
  public IPv4 address.

Then check from outside: on a phone with Wi-Fi off, open `http://NAME`. A page or a redirect means the ports
are open; a timeout means something still blocks them. Caddy's log says the same for the certificate:
`docker compose logs caddy | grep -i -e error -e timeout`.

## Use a Claude or ChatGPT subscription

Yuo can write lessons through the Claude Code or Codex program, signed in to your own subscription, instead
of an API key. Choose it in the setup wizard or in Settings; Yuo then checks that the program is in the
container and signed in before it writes anything, and helps with both:

- Claude Code: Yuo installs the program itself (the vendor's installer, into the data volume) and runs the
  sign-in in your browser: open the link it shows, sign in, paste the code back into Yuo.
- Codex: Yuo installs the program itself too (the vendor's installer, about 500 MB in the data volume) and
  starts a device sign-in: open the link it shows, sign in, and enter the one-time code Yuo displays. Yuo
  notices the sign-in by itself. If the page refuses the code, switch on device sign-in in your ChatGPT
  security settings first.

The programs and their sign-in live in `/data/home` (the `yuo_data` volume), so they survive an update of the
image. To sign in by hand instead: `docker compose exec yuo claude auth login` or
`docker compose exec yuo codex login --device-auth`.

## Look after it

- Lost every way in: `docker compose exec yuo yuo setup-code` prints a new setup code.
- Backups: one a day, the newest seven, in the `data` volume (`/data/backups`); one now with
  `docker compose exec yuo yuo backup`. Copy them off the machine with
  `docker compose cp yuo:/data/backups ./backups` (and keep `yuo_key` with them).
- Restore: `docker compose stop yuo && docker compose run --rm yuo restore [FILE] && docker compose start yuo`
  (the newest backup by default; the replaced database is kept next to it).
- Continuous replication (optional): [Litestream](https://litestream.io) can stream `/data/yuo.db` to object
  storage from a sidecar sharing the `data` volume; Yuo does not need it, and the daily backups stay on.
- Signed-in devices: Settings > Sign-in and devices; revoke a lost phone there.

## What is where

- `/data`: database, backups, generated media, the render work folder (shared with the render container).
- The app container's root is read-only; it runs as user 10001 with no capabilities.
- The render container has no network (`network_mode: none`) and no secrets: it only runs Yuo's own render
  scripts on work folders the app prepared.
