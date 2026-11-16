"""Network exposure adapters: how other devices reach a server install over HTTPS.

Each adapter ends in the same two facts the app needs: the canonical origin (`YUO_ORIGIN`, which passkeys bind
to) and, for a proxy in front, where to send traffic. The app always keeps its own sign-in.

- Tailscale Serve (the default): private to the learner's tailnet, real certificates, works behind CGNAT.
- Caddy: a public name, either the learner's domain or an sslip.io name derived from the server's IP address,
  with automatic certificates.
- Bring your own proxy: any reverse proxy that keeps the Host header and does not buffer event streams.
"""
