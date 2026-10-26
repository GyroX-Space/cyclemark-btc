# Static Dashboard Hosting

The English-language dashboard is in the web directory and reads JSON records from the repository data archive. It is designed for public read-only hosting and manual editorial screenshots. It does not publish to social media.

## GitHub Pages

1. Open the repository Settings.
2. Open Pages under the Code and automation section.
3. Select deployment from a branch.
4. Select the main branch and the root folder only if the site files are placed at the repository root; otherwise use a GitHub Actions deployment workflow that copies the web directory and data/signals directory into a publish artifact.
5. Confirm the published URL and test that the latest and history JSON paths return valid JSON.

The current page is in the web directory, so a workflow or a deliberate site-root layout is required before Pages can serve it directly. Do not announce a live URL until the deployment has been verified.

## Server hosting (cyclemarket.predi.org)

Production serves the dashboard from the daily-refresh host as a static site.

- Web root: `/srv/cyclemark` on the EC2 instance, owned by the cron user.
- After every refresh, `scripts/run_daily.sh` copies `web/index.html`, `web/i18n/*.json`, and `data/signals/{latest,history}.json` into that directory, so the site matches the 05:05 UTC run without a build or deploy step. The step is skipped on hosts without that directory.
- The nginx site block lives in `/etc/nginx/conf.d/zz-cyclemark.conf`. The `zz-` prefix matters: nginx makes the first `listen 80` block the default server, so an alphabetically earlier file would capture unmatched hosts, including load-balancer health checks.
- TLS and host routing are handled by the `*.predi.org` load balancer in front of the instance; nginx listens on port 80 only.
- DNS: `cyclemarket.predi.org` must resolve to the same load balancer as `predi.org`.

    server {
        listen 80;
        server_name cyclemarket.predi.org;
        root /srv/cyclemark;
        index index.html;
        access_log /var/log/nginx/cyclemark.access.log;
        error_log  /var/log/nginx/cyclemark.error.log notice;
        gzip on;
        gzip_types application/json application/javascript text/css image/svg+xml;
        gzip_min_length 512;
        add_header Cache-Control "no-cache" always;
        location / { try_files $uri $uri/ =404; }
    }

SELinux (Amazon Linux runs it in enforcing mode) must allow nginx to read the web root:

    sudo semanage fcontext -a -t httpd_sys_content_t '/srv/cyclemark(/.*)?'
    sudo restorecon -Rv /srv/cyclemark

Without that rule the site returns 403/404 while file permissions look correct. It also labels files written by later cron runs.

Cache freshness: nginx sends `Cache-Control: no-cache`, and the page requests JSON with `cache: "no-store"` plus a `?_t=YYYYMMDD` token, so browsers never serve yesterday's archive. `history.json` is about 7.5 MB raw and about 370 KB gzipped, so keep gzip enabled.

## Languages

All interface text lives in `web/i18n/<locale>.json`; English is the reference pack. To add a language, add a pack with the same keys and register its locale code in `LOCALES` in `web/index.html`. The page follows the browser language on first visit, accepts `?lang=<locale>`, and remembers the choice in localStorage. Packs marked `"_dir": "rtl"` (Arabic) flip the document direction.

## Data paths

The dashboard resolves its data from the first source that answers, in this order:

1. `data/signals/` — same-origin, served from `/srv/cyclemark/data/signals/`
2. `../data/signals/` — used when the page is served under `/web/` with the repository root as document root
3. `https://raw.githubusercontent.com/GyroX-Space/cyclemark-btc/main/data/signals/` — fallback when only the HTML is deployed

It expects:
- data/signals/latest.json
- data/signals/history.json

If no source answers, the page displays an archive-unavailable message rather than fabricating content. When the GitHub fallback is in use, freshness depends on the daily push to `main`; check `data/last_run.json` if the displayed date looks stale. The hover title on the status badge shows which source answered.

## Editorial capture

The layout is responsive and includes a print stylesheet. For clean screenshots, use a desktop viewport, wait until the archive badge shows that data loaded, and capture the dashboard or calendar month. Missing dates remain empty; data-only dates use a neutral calendar color. Do not imply that a data-only record is a validated market state.
