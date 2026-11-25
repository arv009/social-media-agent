"""Canva connector: brand templates, sending images to Canva for editing, and PNG exports.

Setup: CANVA_CLIENT_ID / CANVA_CLIENT_SECRET in .env, then `python scripts/canva_login.py`.
Brand templates and autofill need Canva Pro, Teams or Enterprise; the other tools work on any plan.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent.canva_api import CanvaClient, CanvaError, download
from social_agent.graphics import EXPORT_DIR, SIZES

mcp = MCPServer("canva")
_client: CanvaClient | None = None


def client() -> CanvaClient:
    global _client
    if _client is None:
        try:
            _client = CanvaClient()
        except CanvaError as e:
            raise ToolError(str(e)) from e
    return _client


def _project_file(path: str) -> Path:
    p = (ROOT / path).resolve()
    if ROOT.resolve() not in p.parents or not p.is_file():
        raise ToolError(f"{path} is not an existing file inside the project folder.")
    return p


def _export(design_id: str, platform: str, title: str) -> dict:
    width = SIZES.get(platform, (1080, 1080))[0]
    urls = client().export_png(design_id, width=width)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or design_id
    local = download(urls[0], EXPORT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-canva-{slug}.png")
    return {"image_path": str(local.relative_to(ROOT)), "public_image_url": urls[0],
            "public_url_note": "Canva download links expire after 24 hours; publish to Instagram before then "
                               "or export again.", "pages": len(urls)}


@mcp.tool()
def list_brand_templates(query: str | None = None, limit: int = 20) -> str:
    """List the brand's Canva templates (needs Canva Pro, Teams or Enterprise).

    Args:
        query: Optional search words, e.g. "instagram quote".
        limit: Maximum number of templates.
    """
    try:
        items = client().list_brand_templates(query, limit)
    except CanvaError as e:
        raise ToolError(str(e)) from e
    return to_json([{"id": t["id"], "title": t.get("title"), "view_url": t.get("view_url")} for t in items])


@mcp.tool()
def get_template_fields(template_id: str) -> str:
    """The fields a brand template can autofill, e.g. {"headline": "text", "photo": "image"}."""
    try:
        dataset = client().template_fields(template_id)
    except CanvaError as e:
        raise ToolError(str(e)) from e
    if not dataset:
        return "This template has no autofill fields. Add data fields to it in Canva first."
    return to_json({name: f["type"] for name, f in dataset.items()})


@mcp.tool()
def create_from_template(template_id: str, fields_json: str, title: str, platform: str = "instagram",
                         export_png: bool = True) -> str:
    """Fill a brand template with text (and images) to make a new Canva design, then export it as a PNG.

    Args:
        template_id: From list_brand_templates.
        fields_json: JSON object of field name -> value. Text fields take a string. Image fields take a
            project image path, e.g. {"headline": "5 lessons", "photo": "data/exports/photo.png"}.
        title: Name for the new design.
        platform: instagram, facebook or linkedin (sets the export width).
        export_png: Also export and download the finished image.
    """
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError as e:
        raise ToolError(f"fields_json is not valid JSON ({e}).") from e
    try:
        dataset = client().template_fields(template_id)
        data = {}
        for name, value in fields.items():
            kind = dataset.get(name, {}).get("type", "text")
            if kind == "image":
                data[name] = {"type": "image", "asset_id": client().upload_asset(_project_file(str(value)))}
            else:
                data[name] = {"type": "text", "text": str(value)}
        design = client().autofill(template_id, data, title)
        result = {"design_id": design["id"], "edit_url": design.get("urls", {}).get("edit_url")}
        if export_png:
            result.update(_export(design["id"], platform.lower(), title))
    except CanvaError as e:
        raise ToolError(str(e)) from e
    unknown = sorted(set(fields) - set(dataset))
    if unknown:
        result["warning"] = f"Canva ignored unknown fields: {unknown}"
    return to_json(result)


@mcp.tool()
def send_image_to_canva(image_path: str, title: str, platform: str = "instagram") -> str:
    """Upload a project image (e.g. from make_post_graphic) to Canva as a new design sized for the platform,
    so the reviewer can polish it in Canva. Returns the design id and edit link (pass the link as
    design_link when submitting the draft).

    Args:
        image_path: Image inside the project, e.g. "data/exports/20261201-instagram-5-lessons.png".
        title: Name for the design in Canva.
        platform: instagram, facebook or linkedin.
    """
    w, h = SIZES.get(platform.lower(), (1080, 1080))
    try:
        asset_id = client().upload_asset(_project_file(image_path), name=title)
        design = client().create_design(title, w, h, asset_id=asset_id)
    except CanvaError as e:
        raise ToolError(str(e)) from e
    return to_json({"design_id": design["id"], "edit_url": design["urls"]["edit_url"],
                    "note": "Edit links are valid for 30 days."})


@mcp.tool()
def export_design(design_id: str, platform: str = "instagram", title: str = "") -> str:
    """Export a Canva design as PNG (e.g. after the reviewer edited it). Downloads it to data/exports
    and returns a public URL that Instagram publishing can use (valid 24 hours).

    Args:
        design_id: The Canva design id.
        platform: instagram, facebook or linkedin (sets the export width).
        title: Optional name used for the downloaded file.
    """
    try:
        return to_json(_export(design_id, platform.lower(), title or design_id))
    except CanvaError as e:
        raise ToolError(str(e)) from e


if __name__ == "__main__":
    mcp.run()
