# Running the portal on SharePoint

In SharePoint mode the portal keeps **all of its data in your SharePoint site**:

| What | Where in SharePoint |
|---|---|
| Applications, verifications, corrections, approvals, locks, users, masters, notifications, audit trail, settings | 24 lists, `RTPS_Applications`, `RTPS_AuditLogs`, … (one per table) |
| Attachments | The **RTPS Documents** library, one folder per application, with SharePoint's own version history |
| Saved reports | The **RTPS Reports** library, one folder per report |
| Sign-in | Microsoft 365 (Entra ID) accounts, matched to portal users by email |

Roles and permissions are still assigned in the portal (User Management, Role
Management).

## How it works

Each list has a `RecordId` column (the portal's id for the row) and a typed
column for every field. The portal keeps a local cache of the lists so its
screens stay fast:

- **Every change** made in the portal is queued and sent to SharePoint at the
  end of the page that made it. If SharePoint is unreachable, changes wait in
  the queue and go as soon as it answers. The sidebar says how many are waiting.
- **Changes made in SharePoint** — edited in the browser, or by Power Automate —
  reach the portal within 30 seconds, through Graph's delta queries. A list
  item added directly in SharePoint gets a `RecordId` written back to it.
- **Conflicts:** a portal change that has not been sent yet is never
  overwritten; after that, the last write wins.
- **Settings → SharePoint** shows the queue, the last sync and any error, and
  has *Sync now*, *Re-read everything* and *Check the lists*.

Two things never go to SharePoint: password hashes (there are none: sign-in is
Microsoft 365) and file bytes in list items (they go to the library instead).

## Setting it up

You need: a SharePoint site for the portal, rights to register an app in
Microsoft Entra ID, and an administrator who can grant admin consent.

### 1. Register the app in Entra ID

Entra admin centre → **App registrations** → **New registration**.

- Name: `RTPS QAP Portal`
- Supported account types: *this organisational directory only*
- Redirect URI: **Web**, `https://<your portal address>/oauth2callback`
  (for a local trial: `http://localhost:8501/oauth2callback`)

Then, in the registration:

1. **Certificates & secrets** → *New client secret*. Copy the value now; it is
   shown once.
2. **Token configuration** → *Add optional claim* → ID token → `email`.
3. Note the **Application (client) ID** and **Directory (tenant) ID** from the
   overview.

### 2. Give it access to the one site, and nothing else

Under **API permissions** → *Add a permission* → Microsoft Graph →
**Application permissions** → `Sites.Selected`, then **Grant admin consent**.

`Sites.Selected` grants nothing until the site itself is granted. A SharePoint
or Global administrator grants it — for example in Graph Explorer:

```http
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
Content-Type: application/json

{
  "roles": ["manage"],
  "grantedToIdentities": [{
    "application": { "id": "<client id>", "displayName": "RTPS QAP Portal" }
  }]
}
```

Get `{site-id}` with
`GET https://graph.microsoft.com/v1.0/sites/<tenant>.sharepoint.com:/sites/<site>`.

`manage` is needed once, to create the lists. After provisioning you may lower
it to `write`, which is all the running portal needs.

(If your organisation prefers it, `Sites.ReadWrite.All` also works, but it
reaches every site in the tenant.)

Sign-in itself needs only the delegated `openid`, `profile` and `email`
permissions, which every registration has.

### 3. Fill in `.streamlit/secrets.toml`

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (it is
git-ignored) and fill it in:

```toml
[sharepoint]
enabled = true
tenant_id = "<directory (tenant) id>"
client_id = "<application (client) id>"
client_secret = "<client secret value>"
site_hostname = "<tenant>.sharepoint.com"
site_path = "/sites/<site>"
bootstrap_admin_email = "<your work email>"

[auth]
redirect_uri = "https://<your portal address>/oauth2callback"
cookie_secret = "<a long random string>"

[auth.microsoft]
client_id = "<application (client) id>"
client_secret = "<client secret value>"
server_metadata_url = "https://login.microsoftonline.com/<tenant id>/v2.0/.well-known/openid-configuration"
```

On a server or in a container you can use environment variables instead of the
`[sharepoint]` section: `RTPS_SP_ENABLED=1`, `RTPS_SP_TENANT_ID`,
`RTPS_SP_CLIENT_ID`, `RTPS_SP_CLIENT_SECRET`, `RTPS_SP_SITE_HOSTNAME`,
`RTPS_SP_SITE_PATH`, `RTPS_SP_BOOTSTRAP_ADMIN_EMAIL`. For a sovereign cloud set
`RTPS_SP_GRAPH_URL` and `RTPS_SP_LOGIN_URL` (or `graph_url` / `login_url`).

### 4. Create the lists

From the project folder:

```
uv run python -m app.sharepoint.provision
```

This creates the 24 lists and both libraries, and loads the reference data:
roles, permissions, Bihar's divisions, districts, blocks and offices,
departments and services. Running it again only adds what is missing.

To bring existing data across instead:

```
uv run python -m app.sharepoint.provision --migrate rtps_qap.db
```

or, for a trial, the demo data set:

```
uv run python -m app.sharepoint.provision --seed-demo
```

### 5. Start the portal and sign in

```
uv run streamlit run streamlit_app.py
```

Sign in with Microsoft 365 as the `bootstrap_admin_email` account. It becomes
the Super Admin — only while the site has no other active Super Admin. Then add
everyone else in **User Management**, by the email address of their Microsoft
365 account.

## Things to know

- **Run one portal instance per site.** The portal hands out record ids; two
  instances writing to the same lists could hand out the same one.
- **List views over 5,000 items.** SharePoint's list view threshold applies to
  people browsing the lists, not to the portal, which pages through Graph.
  Index the columns you filter by in SharePoint views (`Status`,
  `DistrictId` on `RTPS_Applications`) when the lists grow.
- **Who can see the lists.** Anyone with access to the site can read the lists
  directly, outside the portal's roles and district scope. Give staff access to
  the portal, not the site; keep the site to administrators.
- **Throttling.** The portal batches its writes (20 per request) and waits as
  long as SharePoint asks when throttled.
- **Uploads** are limited to 200 MB per file (the portal's upload limit; Graph's single-request upload allows up to 250 MB).
- **Edits in SharePoint** bypass the portal's workflow rules and audit trail.
  Treat direct edits as an administrator's tool.

## Back to the local database

Set `enabled = false` (or remove the `[sharepoint]` section). The portal goes
back to `rtps_qap.db` and the demo accounts with passwords.
