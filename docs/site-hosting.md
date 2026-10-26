# Static Dashboard Hosting

The English-language dashboard is in the web directory and reads JSON records from the repository data archive. It is designed for public read-only hosting and manual editorial screenshots. It does not publish to social media.

## GitHub Pages

1. Open the repository Settings.
2. Open Pages under the Code and automation section.
3. Select deployment from a branch.
4. Select the main branch and the root folder only if the site files are placed at the repository root; otherwise use a GitHub Actions deployment workflow that copies the web directory and data/signals directory into a publish artifact.
5. Confirm the published URL and test that the latest and history JSON paths return valid JSON.

The current page is in the web directory, so a workflow or a deliberate site-root layout is required before Pages can serve it directly. Do not announce a live URL until the deployment has been verified.

## Server hosting on a subdomain

The production plan is to serve the dashboard from the daily-refresh server on its own subdomain, with no GitHub Actions involved. The repository remains the single source of truth: the cron job pulls, generates, and pushes every day, and the web server reads the same `data/signals/` files in place.

Recommended nginx layout (the page is served at the subdomain root, data at `/data/signals/`):

    server {
        listen 80;
        server_name btc.example.com;
        root /home/ec2-user/simon/cyclemark-btc;

        location = / { try_files /web/index.html =404; }
        location /web/ { try_files $uri =404; }
        location /data/signals/ {
            add_header Cache-Control "no-cache" always;
            try_files $uri =404;
        }
        location / { return 404; }
    }

Notes:

- Set `root` to the checkout used by `run_daily.sh` so every cron run refreshes the served JSON with no copy or build step.
- Serve the JSON with a revalidating cache header; the dashboard itself already requests it with `cache: "no-store"`.
- Enable TLS (for example with certbot) and gzip for `application/json`; `history.json` is several megabytes uncompressed.
- The daily job runs at 05:05 UTC. `data/signals/latest.json` always carries `generated_at_utc`, which the dashboard displays as its "Updated" timestamp.

## Data paths

The dashboard resolves its data from the first source that answers, in this order:

1. `data/signals/` — same-origin path, used when the page is served at the subdomain root or with an nginx `/data/` mapping
2. `../data/signals/` — used when the page is served under `/web/` with the repository root as document root
3. `https://raw.githubusercontent.com/GyroX-Space/cyclemark-btc/main/data/signals/` — fallback when only the HTML is deployed

It expects:
- data/signals/latest.json
- data/signals/history.json

If no source answers, the page displays an archive-unavailable message rather than fabricating content. When the GitHub fallback is in use, freshness depends on the daily push to `main`; check `data/last_run.json` if the displayed date looks stale. The hover title on the status badge shows which source answered.

## Editorial capture

The layout is responsive and includes a print stylesheet. For clean screenshots, use a desktop viewport, wait until the archive badge shows that data loaded, and capture the dashboard or calendar month. Missing dates remain empty; data-only dates use a neutral calendar color. Do not imply that a data-only record is a validated market state.
