# Publishing at aitipster.net via Cloudflare Tunnel (CLI)

Replaces ngrok. Free, stable custom domain, no rotating URL. The tunnel runs on
this Mac and forwards `aitipster.net` → `localhost:3000`.

We use the **cloudflared CLI** (not the Zero Trust dashboard — its menus keep
moving and it needs separate onboarding). This way there's no token and no
dashboard hunting.

## One-time setup (~10 min)

### 1. Install cloudflared
```bash
brew install cloudflared
```

### 2. Authorise + create the tunnel
```bash
# Opens a browser — pick the aitipster.net zone and authorise.
cloudflared tunnel login

# Creates the tunnel + writes credentials to ~/.cloudflared/<UUID>.json
cloudflared tunnel create aitipster

# Point the domain(s) at the tunnel (creates the DNS records automatically)
cloudflared tunnel route dns aitipster aitipster.net
cloudflared tunnel route dns aitipster www.aitipster.net
```
That's it — no config file, no token. Credentials live in `~/.cloudflared/`.

### 3. Set the public URLs in `.env`
```dotenv
NEXTAUTH_URL=https://aitipster.net          # CRITICAL — auth breaks otherwise
NEXT_PUBLIC_SITE_URL=https://aitipster.net
ALLOWED_DEV_ORIGINS=aitipster.net,www.aitipster.net
```

### 4. Update Google OAuth (if using Google sign-in)
Google Cloud Console → Credentials → your OAuth client → **Authorized redirect URIs**,
add: `https://aitipster.net/api/auth/callback/google`

### 5. Start the tunnel service + rebuild the frontend
```bash
bash launchd/install.sh          # loads com.football-predictor.cloudflared (always on)
docker compose up -d             # picks up the new NEXTAUTH_URL / SITE_URL env
./scripts/deploy_frontend.sh     # rebuild so SSR uses the new URLs
```

### 6. Verify
```bash
cloudflared tunnel list          # shows "aitipster" with a connection
curl -I https://aitipster.net    # 200/307, served from your box via Cloudflare
```

## Test the tunnel once before installing the service (optional)
```bash
cloudflared tunnel run --url http://localhost:3000 aitipster
# Ctrl-C when you've confirmed https://aitipster.net loads.
```
The launchd plist runs exactly this command (binary invoked directly — a wrapper
script inside ~/Documents would be blocked by macOS TCC with "Operation not
permitted" when launched from launchd).

## Notes
- Tunnel name (`aitipster`) and target (`http://localhost:3000`) are baked into
  the plist's ProgramArguments — edit `com.football-predictor.cloudflared.plist`
  and re-run `bash launchd/install.sh` to change them.
- ngrok has been fully removed (plist, .env keys, docs) — Cloudflare is the only
  tunnel now.
- Capacity bottleneck is this Mac (SSR + DB per request), not Cloudflare. When
  traffic grows, add short-TTL page caching or move the origin to a VPS — the
  domain and tunnel stay the same.
