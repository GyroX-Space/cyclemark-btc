# Static Dashboard Hosting

The English-language dashboard is in the web directory and reads JSON records from the repository data archive. It is designed for public read-only hosting and manual editorial screenshots. It does not publish to social media.

## GitHub Pages

1. Open the repository Settings.
2. Open Pages under the Code and automation section.
3. Select deployment from a branch.
4. Select the main branch and the root folder only if the site files are placed at the repository root; otherwise use a GitHub Actions deployment workflow that copies the web directory and data/signals directory into a publish artifact.
5. Confirm the published URL and test that the latest and history JSON paths return valid JSON.

The current page is in the web directory, so a workflow or a deliberate site-root layout is required before Pages can serve it directly. Do not announce a live URL until the deployment has been verified.

## Editorial capture

The layout is responsive and includes a print stylesheet. For clean screenshots, use a desktop viewport, wait until the archive badge shows that data loaded, and capture the dashboard or calendar month. Missing dates remain empty; data-only dates use a neutral calendar color. Do not imply that a data-only record is a validated market state.

## Data paths

The dashboard expects:
- data/signals/latest.json
- data/signals/history.json

If these files are absent, the page displays an archive-unavailable message rather than fabricating content.
