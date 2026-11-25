"""Google Drive connector: find and read brand assets, briefs and docs; upload files.

One-time setup:
  1. Google Cloud Console -> create a project -> enable the Google Drive API
  2. OAuth consent screen (External, add yourself as a test user)
  3. Credentials -> OAuth client ID -> Desktop app -> download JSON
     and save it as secrets/google_credentials.json
  4. Run:  python scripts/google_login.py   (opens your browser once, saves secrets/google_token.json)
"""
import io

from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("google-drive")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file"]
TOKEN_PATH = ROOT / "secrets/google_token.json"
EXPORT_TYPES = {  # Google-native files have to be exported to read them
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_service = None


def drive():
    global _service
    if _service is None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not TOKEN_PATH.exists():
            raise RuntimeError("Not logged in to Google. Run: python scripts/google_login.py")
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink,size)"


@mcp.tool()
def search_files(query: str, limit: int = 20) -> str:
    """Search Google Drive by file name or content.

    Args:
        query: Words to look for, e.g. "brand guidelines" or "December campaign".
        limit: Maximum number of results.
    """
    try:
        q = query.replace("'", "\\'")
        res = drive().files().list(q=f"(name contains '{q}' or fullText contains '{q}') and trashed = false",
                                   pageSize=limit, fields=FIELDS, orderBy="modifiedTime desc").execute()
    except Exception as e:  # noqa: BLE001 - report any Google error to the agent
        raise ToolError(f"{e}")
    return to_json(res.get("files", []))


@mcp.tool()
def list_folder(folder_id: str = "root", limit: int = 50) -> str:
    """List files in a Drive folder ("root" for My Drive)."""
    try:
        res = drive().files().list(q=f"'{folder_id}' in parents and trashed = false", pageSize=limit,
                                   fields=FIELDS, orderBy="folder,name").execute()
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"{e}")
    return to_json(res.get("files", []))


@mcp.tool()
def read_file(file_id: str, max_chars: int = 20000) -> str:
    """Read the text of a Google Doc, Sheet (as CSV), Slides deck, or a plain text / CSV / markdown file.

    Args:
        file_id: The file id (from search_files or list_folder).
        max_chars: Cut-off for very long files.
    """
    from googleapiclient.http import MediaIoBaseDownload
    try:
        meta = drive().files().get(fileId=file_id, fields="name,mimeType").execute()
        mime = meta["mimeType"]
        if mime in EXPORT_TYPES:
            request = drive().files().export_media(fileId=file_id, mimeType=EXPORT_TYPES[mime])
        elif mime.startswith("text/") or mime in ("application/json", "text/csv"):
            request = drive().files().get_media(fileId=file_id)
        else:
            return f"'{meta['name']}' is {mime}; only docs, sheets, slides and text files can be read."
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"{e}")
    text = buf.getvalue().decode("utf-8", errors="replace")
    suffix = f"\n\n[cut off at {max_chars} of {len(text)} characters]" if len(text) > max_chars else ""
    return f"# {meta['name']}\n\n{text[:max_chars]}{suffix}"


@mcp.tool()
def upload_file(local_path: str, folder_id: str | None = None) -> str:
    """Upload a file from this project (e.g. an exported design or report) to Google Drive.

    Args:
        local_path: Path relative to the project folder, e.g. "data/exports/post_12.png".
        folder_id: Optional Drive folder id to upload into.
    """
    from googleapiclient.http import MediaFileUpload
    path = (ROOT / local_path).resolve()
    if ROOT.resolve() not in path.parents or not path.is_file():
        raise ToolError("local_path must be an existing file inside the project folder.")
    body = {"name": path.name, **({"parents": [folder_id]} if folder_id else {})}
    try:
        f = drive().files().create(body=body, media_body=MediaFileUpload(str(path)),
                                   fields="id,name,webViewLink").execute()
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"{e}")
    return to_json(f)


if __name__ == "__main__":
    mcp.run()
