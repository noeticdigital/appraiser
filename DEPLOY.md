# Deploying the Multifactorial MPI

The app is a single static page (`index.html` + `lb-logo.svg`). No backend.

- **GitHub Pages** — serves `main` automatically at
  https://noeticdigital.github.io/appraiser/
- **EC2 (Noetic OS box)** — nginx serves `/var/www/appraiser/` at
  http://3.131.110.117/appraiser/ . To update:
  `scp index.html lb-logo.svg ubuntu@3.131.110.117:/tmp/` then move into
  `/var/www/appraiser/` with sudo.

## Auth model

Bring-your-own Anthropic API key, gated by an access passcode. The passcode is
checked client-side as a SHA-256 hash (`PASS_HASH` in `index.html`) — the
plaintext never ships. To change it:

    printf '%s' "new-passcode" | shasum -a 256

and paste the hex into `PASS_HASH`. The user's API key goes directly from
their browser to api.anthropic.com and is stored only in their localStorage.

History: an earlier version ran a passcode-gated proxy on the EC2 box holding
a shared server-side key (`server/` in git history). That mode was removed —
the proxy service, its key file, and the nginx API route were decommissioned.
