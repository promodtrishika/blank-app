"""Build the Microsoft Teams app package for the portal.

    uv run python -m app.teams_package --url https://rtps-qap.azurewebsites.net

Writes rtps-qap-teams.zip: manifest.json plus the two icons Teams needs. Upload
it in the Teams admin centre (Manage apps -> Upload new app), or, for a trial,
in Teams itself (Apps -> Manage your apps -> Upload an app).

The tab shows a launcher page (`/?from=teams`). Microsoft's sign-in page
refuses to load inside a Teams frame, so the portal opens in the browser.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

BLUE = (42, 120, 214)        # theme primary (#2a78d6)
MANIFEST_VERSION = "1.17"
SCHEMA = (f"https://developer.microsoft.com/json-schemas/teams/v{MANIFEST_VERSION}"
          "/MicrosoftTeams.schema.json")


def _shield(size: int, fill, background) -> bytes:
    """A shield with a tick: the portal's mark, drawn at any size."""
    scale = 4                                   # draw large, then downsample
    s = size * scale
    img = Image.new("RGBA", (s, s), background)
    d = ImageDraw.Draw(img)
    m = s * 0.18
    top, bottom = m, s - m * 0.8
    left, right = m * 1.1, s - m * 1.1
    mid = s / 2
    shield = [(mid, top), (right, top + s * 0.1), (right, mid),
              (mid, bottom), (left, mid), (left, top + s * 0.1)]
    d.polygon(shield, outline=fill, width=max(scale, int(s * 0.06)))
    w = max(scale, int(s * 0.07))
    d.line([(mid - s * 0.15, mid - s * 0.02), (mid - s * 0.03, mid + s * 0.1),
            (mid + s * 0.17, mid - s * 0.13)], fill=fill, width=w, joint="curve")
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def color_icon() -> bytes:
    """192 x 192, full colour."""
    return _shield(192, (255, 255, 255, 255), BLUE + (255,))


def outline_icon() -> bytes:
    """32 x 32, white on transparent, as Teams requires."""
    return _shield(32, (255, 255, 255, 255), (0, 0, 0, 0))


def manifest(url: str, name: str = "RTPS QAP Portal",
             developer: str = "RTPS Cell") -> dict:
    url = url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("The portal URL must be https://… — Teams only opens https pages.")
    host = parts.netloc
    return {
        "$schema": SCHEMA,
        "manifestVersion": MANIFEST_VERSION,
        "version": "1.0.0",
        # Stable for a given address, so a re-upload updates the same app.
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, url)),
        "developer": {
            "name": developer,
            "websiteUrl": url,
            "privacyUrl": url,
            "termsOfUseUrl": url,
        },
        "name": {"short": name[:30], "full": f"{name} — Right to Public Services"[:100]},
        "description": {
            "short": "Verification, correction, approval and audit for RTPS applications."[:80],
            "full": ("The Quality Assurance Portal for Right to Public Services: "
                     "application entry, QAP verification, corrections, the approval "
                     "chain, lock and unlock, reports and the audit trail. Records are "
                     "kept in SharePoint; sign-in is your Microsoft 365 account."),
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": "#2A78D6",
        "staticTabs": [{
            "entityId": "rtps-qap-portal",
            "name": "Portal",
            "contentUrl": f"{url}/?from=teams",
            "websiteUrl": url,
            "scopes": ["personal"],
        }],
        "permissions": ["identity"],
        "validDomains": [host],
    }


def build(url: str, out: Path, name: str, developer: str) -> Path:
    data = manifest(url, name, developer)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(data, indent=2, ensure_ascii=False))
        z.writestr("color.png", color_icon())
        z.writestr("outline.png", outline_icon())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Teams app package.")
    ap.add_argument("--url", required=True,
                    help="the portal's https address, e.g. https://rtps-qap.azurewebsites.net")
    ap.add_argument("--out", default="rtps-qap-teams.zip")
    ap.add_argument("--name", default="RTPS QAP Portal")
    ap.add_argument("--developer", default="RTPS Cell",
                    help="the organisation shown as the app's publisher")
    args = ap.parse_args(argv)
    try:
        path = build(args.url, Path(args.out), args.name, args.developer)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Wrote {path}. Upload it in the Teams admin centre: Manage apps -> "
          "Upload new app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
