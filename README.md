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
4. In the **Environment** tab, add these two variables:
   - `TELEGRAM_API_ID` = your api_id
   - `TELEGRAM_API_HASH` = your api_hash
   *(the bot token itself does NOT go here -- it stays in your bot code, as part of the request URL)*
5. **Instance Type**: leave it on Free. Since this server is only hit for large-file streaming, occasional cold-starts (30-60s to wake up) are expected and fine -- no need to keep it always-on.
6. Deploy. Once the build finishes, Render gives you a URL like:
   `https://your-service.onrender.com`

## What to change in your bot code

Route requests conditionally based on file size -- small files keep using the default Telegram API, large files (>20MB) go to your self-hosted server:

```js
const SELF_HOSTED_BASE = "https://your-service.onrender.com";
const DEFAULT_BASE = "https://api.telegram.org";
const SIZE_LIMIT = 20 * 1024 * 1024; // 20MB

function getApiBase(fileSizeBytes) {
  return fileSizeBytes > SIZE_LIMIT ? SELF_HOSTED_BASE : DEFAULT_BASE;
}
```

In libraries like grammY/Telegraf, this is usually a per-request or per-client `apiRoot`/base URL option -- no need to hardcode full URLs everywhere.

**Since the self-hosted server sleeps when idle (free tier), add retry-with-backoff around calls to it** (e.g. 2-3 retries, 5-10s apart) so a cold-start doesn't show up as a hard failure on the first large-file request.

## Testing

After deploying, check with a browser or curl:

```
https://your-service.onrender.com/bot<TOKEN>/getMe
```

If you get back your bot's info as JSON, the server is working correctly.

## Things to keep in mind

- **Free tier has an ephemeral filesystem** -- cache/temp files are wiped on every restart/redeploy. Fine for this proxy-style, occasional use case.
- **`--local` mode is enabled** -> the file size limit jumps from 20MB to several GB, but Telegram then returns a local file path instead of a downloadable URL for large files -- your bot code needs to handle that (read the file from the server's local path/response rather than expecting a normal Bot API file URL).
- **Free tier spin-down** -- after inactivity it sleeps; the next request can take 30-60s to wake it. Since this server is only used "sometimes" (for large files), this is expected and acceptable -- no need for UptimeRobot or self-pinging here.
- Never commit `api_id` / `api_hash` to a public repo -- keep them only in Render's Environment variables (`.env` is for local testing only, and is already in `.gitignore`).
