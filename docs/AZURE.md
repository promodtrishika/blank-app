# Running the portal on Microsoft's cloud (Azure App Service)

Microsoft 365 itself — SharePoint and Teams — does not run Python code. The
portal runs on **Azure App Service**, Microsoft's hosting service, keeps its
data in **SharePoint** (see [SHAREPOINT.md](SHAREPOINT.md)), and shows up in
**Teams** and on the **SharePoint site** as an app and a link.

```
 Staff ──► Teams tab / SharePoint link ──► Azure App Service (this code) ──► SharePoint lists & libraries
                                                │
                                                └── sign-in: Microsoft 365 (Entra ID)
```

Every push to `main` on GitHub tests the code and deploys it.

## What you need

- An **Azure subscription** in the same organisation as your Microsoft 365
  (App Service is billed monthly; the B1 plan is enough to start).
- The SharePoint setup from [SHAREPOINT.md](SHAREPOINT.md), steps 1–2 (app
  registration and site permission). The same app registration is used here.
- Admin rights in the GitHub repository.

## 1. Create the web app

Azure portal (portal.azure.com) → **Create a resource** → **Web App**:

| Field | Value |
|---|---|
| Resource group | new, e.g. `rtps-qap` |
| Name | e.g. `rtps-qap` → the address becomes `https://rtps-qap.azurewebsites.net` (some regions add a suffix; use the address Azure shows) |
| Publish | **Code** |
| Runtime stack | **Python 3.14** |
| Operating system | **Linux** |
| Region | Central India (or nearest) |
| Pricing plan | **Basic B1** or higher (not Free: it sleeps and has no Always On) |

## 2. Configure it

In the web app:

**Settings → Configuration → General settings**
- **Startup Command:** `bash startup.sh`
- **Web sockets:** On (the portal needs them)
- **Always on:** On
- **Session affinity:** On
- **SCM Basic Auth Publishing Credentials:** On (needed for the GitHub deploy below)

**Settings → Health check:** path `/_stcore/health`

**Settings → Scale out:** **1 instance** — always. The portal keeps one
SharePoint sync queue; two instances would compete.

**Settings → Environment variables → App settings** — add:

| Name | Value |
|---|---|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |
| `WEBSITES_ENABLE_APP_SERVICE_STORAGE` | `true` |
| `RTPS_SP_ENABLED` | `1` |
| `RTPS_SP_TENANT_ID` | Directory (tenant) ID |
| `RTPS_SP_CLIENT_ID` | Application (client) ID |
| `RTPS_SP_CLIENT_SECRET` | client secret — better as a Key Vault reference, see below |
| `RTPS_SP_SITE_HOSTNAME` | `<tenant>.sharepoint.com` |
| `RTPS_SP_SITE_PATH` | `/sites/RTPS-QAP` |
| `RTPS_SP_BOOTSTRAP_ADMIN_EMAIL` | the first administrator's work email |

That is all sign-in needs too: at startup, `startup.sh` writes Streamlit's
sign-in settings from these (same app registration, redirect address
`https://<WEBSITE_HOSTNAME>/oauth2callback`, a cookie secret kept on the app's
persistent storage). To use a separate registration or address, also set
`RTPS_AUTH_CLIENT_ID`, `RTPS_AUTH_CLIENT_SECRET`, `RTPS_AUTH_TENANT_ID`,
`RTPS_AUTH_REDIRECT_URI` or `RTPS_AUTH_COOKIE_SECRET`.

**Keeping the secret in Key Vault (recommended):** store the client secret in
an Azure Key Vault, turn on the web app's **Identity → System assigned**, give
that identity *Key Vault Secrets User* on the vault, and set the setting's value
to `@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/<name>/)`.

## 3. Add the address to the app registration

Entra admin centre → **App registrations** → *RTPS QAP Portal* →
**Authentication** → under **Web**, add the redirect URI:

```
https://rtps-qap.azurewebsites.net/oauth2callback
```

(with your app's real address).

## 4. Connect GitHub so pushes deploy

1. In the web app, **Overview → Download publish profile**.
2. In GitHub, the repository → **Settings → Secrets and variables → Actions**:
   - **Secrets** → *New repository secret* → `AZURE_WEBAPP_PUBLISH_PROFILE`,
     paste the whole file's contents.
   - **Variables** → *New repository variable* → `AZURE_WEBAPP_NAME` = the web
     app's name (e.g. `rtps-qap`).
3. Merge the pull request into `main` (or run **Actions → Test and deploy to
   Azure → Run workflow**). The workflow runs the tests, then deploys. The first
   build takes a few minutes.

Until both settings exist, the workflow only runs the tests.

## 5. Provision SharePoint and sign in

If you have not yet created the lists, do it once from any computer with the
code (SHAREPOINT.md, step 4):

```
uv run python -m app.sharepoint.provision
```

Then open `https://rtps-qap.azurewebsites.net` and sign in with the bootstrap
administrator's Microsoft 365 account. Add everyone else in **User Management**.

## 6. Put it in Teams and on SharePoint

**Teams app**

```
uv run python -m app.teams_package --url https://rtps-qap.azurewebsites.net --developer "Your department"
```

This writes `rtps-qap-teams.zip`. A Teams administrator uploads it: Teams admin
centre → **Teams apps → Manage apps → Upload new app**, and can pin it for
everyone through a setup policy.

The tab shows a launcher with an **Open the RTPS QAP Portal** button. Microsoft
does not allow its sign-in page inside a Teams frame, so the portal opens in the
browser; that is a Microsoft restriction, not a setting.

**SharePoint site**: on the site, **Edit** the navigation → **+ Link** →
the portal's address, label *RTPS QAP Portal*.

## Where things live on Azure

| What | Where |
|---|---|
| Code | deployed by GitHub; runs from a temporary folder Azure manages |
| Records, documents, reports | SharePoint |
| Sync queue and cache, cookie secret | `/home/data/rtps` — App Service's persistent storage |
| Secrets | App Settings (or Key Vault) — never in the repository |
| Logs | web app → **Log stream** |

## Things to know

- **One instance only** (Scale out = 1).
- A restart or redeploy keeps everyone signed in and keeps any changes still
  waiting for SharePoint (they are on `/home`).
- Without the `RTPS_SP_*` settings the app starts in demo mode with sample
  data and portal passwords — useful for a first trial, not for real records.
