# Self-hosted Telegram Bot API server (Render)

Everything needed to run your own Telegram Bot API server on Render is in this folder. Use case: your main bot runs on `api.telegram.org` as usual, and only switches to this self-hosted server when it needs to stream files larger than Telegram's default 20MB limit.

## What you need

1. **Telegram `api_id` + `api_hash`** (free)
   - Log in at [my.telegram.org](https://my.telegram.org) with your phone number
   - Go to **API development tools**
   - Create an app (any name/platform, doesn't matter) -> you'll get `api_id` and `api_hash`
2. **A Render account** (free tier is fine -- this server only needs to run occasionally, when a large file is being streamed)
3. **Your existing bot token** (from BotFather) -- no changes needed there

## Deploy steps

1. Push this whole folder to a GitHub repo (Render deploys from a Git repo, not directly from a zip).
2. Render dashboard -> **New +** -> **Web Service** -> connect your repo.
3. Render will auto-detect the `Dockerfile` (**Runtime: Docker**) -- no changes needed.
4. In the **Environment** tab, add these three variables:
   - `TELEGRAM_API_ID` = your api_id
   - `TELEGRAM_API_HASH` = your api_hash
   - `LOCAL_FILE_SECRET` = any long random string you generate yourself (e.g. `openssl rand -hex 32`) -- this is a shared secret with your Cloudflare Worker, explained below. **Must be set to the exact same value in both places**, or large-file downloads will fail with a 403.
   *(the bot token itself does NOT go here -- it stays in your bot code, as part of the request URL)*
5. **Instance Type**: leave it on Free. Since this server is only hit for large-file streaming, occasional cold-starts (30-60s to wake up) are expected and fine -- no need to keep it always-on.
6. Deploy. Once the build finishes, Render gives you a URL like:
   `https://your-service.onrender.com`

## Why there's a fileserver.py at all

`--local` mode (needed to lift Telegram's default 20MB download cap) changes what `getFile` returns: instead of a relative path you fetch via `https://.../file/bot<token>/<path>`, it returns an **absolute path on this server's own disk**. That endpoint can't resolve an absolute path, so a remote caller (your Cloudflare Worker) has no normal way to get the bytes for anything that went through `--local` mode.

`fileserver.py` is the fix: it's the only process Render's proxy actually reaches (`start.sh` runs `telegram-bot-api` on an internal-only port instead). It transparently forwards every normal request (`/bot<token>/getMe`, `/bot<token>/getFile`, etc.) to `telegram-bot-api`, and additionally serves `/localfile/<absolute-path>?expires=...&sig=...` directly off disk -- but only when `sig` is a valid HMAC-SHA256 signature (keyed with `LOCAL_FILE_SECRET`) that hasn't expired. Without that check, anyone who saw one `/localfile/` URL could read any file this server has ever cached, for any bot token it's ever served -- there's no other access control on it.

## What to change in your bot code

Route requests conditionally based on file size -- small files keep using the default Telegram API, large files (>20MB) go to your self-hosted server. For files fetched via the self-hosted server, `getFile`'s `file_path` will be an absolute path -- build a signed `/localfile/` URL for it instead of the normal file URL:

```js
const SELF_HOSTED_BASE = "https://your-service.onrender.com";
const DEFAULT_BASE = "https://api.telegram.org";
const SIZE_LIMIT = 20 * 1024 * 1024; // 20MB
const LOCAL_FILE_SECRET = "..."; // same value as set on Render

async function signedLocalFileUrl(absolutePath, ttlSeconds = 300) {
  const expires = Math.floor(Date.now() / 1000) + ttlSeconds;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(LOCAL_FILE_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sigBuf = await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(`${absolutePath}:${expires}`)
  );
  const sig = [...new Uint8Array(sigBuf)].map(b => b.toString(16).padStart(2, "0")).join("");
  return `${SELF_HOSTED_BASE}/localfile/${encodeURIComponent(absolutePath)}?expires=${expires}&sig=${sig}`;
}
```

In libraries like grammY/Telegraf, small-file routing (which API base to call) is usually a per-request or per-client `apiRoot`/base URL option -- no need to hardcode full URLs everywhere. Large-file downloads need the signed-URL approach above regardless of library, since it's not something the Bot API's normal file endpoint supports.

**Since the self-hosted server sleeps when idle (free tier), add retry-with-backoff around calls to it** (e.g. 2-3 retries, 5-10s apart) so a cold-start doesn't show up as a hard failure on the first large-file request.

## Testing

After deploying, check with a browser or curl:

```
https://your-service.onrender.com/bot<TOKEN>/getMe
```

If you get back your bot's info as JSON, the server (and the fileserver.py proxy in front of it) is working correctly. `/localfile/` itself can't be meaningfully tested directly in a browser -- it needs a validly-signed URL, which only your Worker can generate.

## Things to keep in mind

- **Free tier has an ephemeral filesystem** -- cache/temp files are wiped on every restart/redeploy. Fine here: every download re-triggers a fresh `getFile` from Telegram if the local cache is gone, rather than depending on it still being there.
- **`--local` mode is enabled** -> the file size limit jumps from 20MB to several GB, but `getFile` returns a local disk path for such files instead of a normal downloadable URL -- see "Why there's a fileserver.py at all" above for how this repo handles that.
- **Free tier spin-down** -- after inactivity it sleeps; the next request can take 30-60s to wake it. Since this server is only used "sometimes" (for large files), this is expected and acceptable -- no need for UptimeRobot or self-pinging here.
- Never commit `api_id` / `api_hash` / `LOCAL_FILE_SECRET` to a public repo -- keep them only in Render's Environment variables (`.env` is for local testing only, and is already in `.gitignore`).
