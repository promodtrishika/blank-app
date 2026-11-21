"""The two document libraries: RTPS Documents and RTPS Reports.

Attachments go to `RTPS Documents/<application number>/<file name>`. A second
upload of the same file name becomes a new SharePoint version of that file,
so SharePoint's own version history is the document history; each portal
document row remembers the SharePoint version it was.
"""

from __future__ import annotations

from urllib.parse import quote

from app.sharepoint.config import SharePointConfig
from app.sharepoint.graph import GraphClient

MAX_SIMPLE_UPLOAD = 250 * 1024 * 1024   # Graph's limit for a single PUT upload


def folder_for(application_number: str) -> str:
    """A folder name SharePoint accepts: no slashes or reserved characters."""
    bad = '/\\:*?"<>|#%'
    return "".join("-" if ch in bad else ch for ch in application_number).strip(". ")


def _path(*parts: str) -> str:
    return "/".join(quote(p, safe="") for p in parts)


class Libraries:
    def __init__(self, client: GraphClient, config: SharePointConfig):
        self.client = client
        self.config = config

    def _put(self, library: str, parts: tuple[str, ...], data: bytes) -> dict:
        if len(data) > MAX_SIMPLE_UPLOAD:
            raise ValueError("Files over 250 MB need a Graph upload session, which "
                             "the portal does not use; it accepts up to 200 MB.")
        drive = self.client.drive_id(library)
        return self.client.request(
            "PUT", f"drives/{drive}/root:/{_path(*parts)}:/content", data=data,
            headers={"Content-Type": "application/octet-stream"})

    def _current_version(self, drive: str, item_id: str) -> str | None:
        versions = self.client.all(f"drives/{drive}/items/{item_id}/versions")
        if not versions:
            return None
        latest = max(versions, key=lambda v: v.get("lastModifiedDateTime", ""))
        return latest.get("id")

    def upload_document(self, application_number: str, file_name: str,
                        data: bytes) -> dict:
        item = self._put(self.config.documents_library,
                         (folder_for(application_number), file_name), data)
        drive = self.client.drive_id(self.config.documents_library)
        return {
            "sp_item_id": item["id"],
            "sp_version_id": self._current_version(drive, item["id"]),
            "web_url": item.get("webUrl"),
        }

    def download_document(self, sp_item_id: str, sp_version_id: str | None) -> bytes:
        drive = self.client.drive_id(self.config.documents_library)
        current = self._current_version(drive, sp_item_id)
        if sp_version_id and sp_version_id != current:
            resp = self.client.request(
                "GET", f"drives/{drive}/items/{sp_item_id}/versions/"
                       f"{quote(sp_version_id, safe='')}/content", raw=True)
        else:
            resp = self.client.request("GET", f"drives/{drive}/items/{sp_item_id}/content",
                                       raw=True)
        return resp.content

    def versions(self, sp_item_id: str) -> list[dict]:
        drive = self.client.drive_id(self.config.documents_library)
        return self.client.all(f"drives/{drive}/items/{sp_item_id}/versions")

    def save_report(self, report: str, file_name: str, data: bytes) -> str | None:
        item = self._put(self.config.reports_library, (folder_for(report), file_name), data)
        return item.get("webUrl")
