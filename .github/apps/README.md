GitHub App scaffold for qmoi-enhanced sync

This folder contains a minimal scaffold to register a GitHub App and use an
installation token from Actions to perform repository operations (create branches,
push, create PRs) without using a long-lived PAT.

Quick outline:
- Create a GitHub App using the manifest in `manifest.yml` (or manually in GitHub settings).
- Install the app on the upstream org/repo (`thealphakenya/qmoi-enhanced`).
- Use the app's private key and app id to request an installation access token for the repo.
- Store the installation token in Actions secrets (or use the helper script in a workflow to mint tokens at runtime).

Files:
- `manifest.yml` - app registration manifest (minimal example)
- `mint_installation_token.py` - example script to mint an installation token (requires PyJWT, requests)
- `workflow-example.yml` - an Actions workflow example showing how to call the script and use the token

Quick setup (high level):

1) Register the GitHub App
	- Go to https://github.com/settings/apps/new and use the `manifest.yml` or create manually.
	- Set the App permissions to at least: Contents: write, Pull requests: write, Metadata: read.
	- Set the callback URL to a valid URL (for testing you can use https://example.com).

2) Install the App on the upstream org/repo
	- After creating the app, install it on `thealphakenya/qmoi-enhanced`.
	- Note the App ID and the Installation ID (visible in the app settings).

3) Add secrets to this fork repo (Settings → Secrets → Actions):
	- `GH_APP_ID` (the app id)
	- `GH_APP_INSTALLATION_ID` (the installation id)
	- `GH_APP_PRIVATE_KEY` (the PEM contents of the app private key)

4) Trigger `workflow-example.yml` (Actions → Workflows → Example: use GitHub App installation token → Run workflow)
	- The workflow will mint an installation token and place it into the `$INSTALLATION_TOKEN` env var for downstream steps.

5) Point your sync workflow to prefer `INSTALLATION_TOKEN` (already implemented in `scripts/sync_orchestrator.py`).

Security note: keep the private key secret. Prefer using installation tokens created on-demand in Actions (they are short lived).

Note: registering an app requires admin permissions on the target org/repo.
