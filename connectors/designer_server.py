"""Designer connector: makes on-brand post images locally, in the style of the brand's Canva designs.

Uses brand.json for colors, fonts, logo, handle, website and voice. Images are saved to data/exports/.
"""
import json

from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import graphics

mcp = MCPServer("designer")


@mcp.tool()
def brand_guidelines() -> str:
    """The brand's name, handle, website, colors, writing voice and the image layouts available.
    Read this before writing or designing."""
    return to_json(graphics.load_brand())


@mcp.tool()
def make_post_graphic(headline: str, layout: str = "question", subtext: str = "", label: str = "",
                      items_json: str = "", platform: str = "instagram", page: str = "01") -> str:
    """Create a 1080x1080 on-brand image. Returns the image path to pass as image_url when submitting the draft.

    Args:
        headline: The main text. Keep it short: under 8 words for cover/question, under 6 for list.
        layout: cover (carousel first slide: big gold headline), list (numbered tips/steps),
            question (hook or question, condensed uppercase) or card (email-style card with body text).
        subtext: Body text for the card layout (under 25 words).
        label: Small gold tag above the list headline, or the email subject for the card layout.
        items_json: For the list layout: JSON list of 3-5 short items, e.g. ["Post 3x a week", "Reply fast"].
        platform: instagram, facebook or linkedin.
        page: Page number shown on the cover layout, e.g. "01".
    """
    if layout not in graphics.LAYOUTS:
        raise ToolError(f"layout must be one of {graphics.LAYOUTS}")
    items = None
    if items_json:
        try:
            items = [str(i) for i in json.loads(items_json)]
        except (json.JSONDecodeError, TypeError) as e:
            raise ToolError(f"items_json must be a JSON list of strings ({e}).") from e
    if layout == "list" and not items:
        raise ToolError("The list layout needs 3-5 items in items_json.")
    if len(headline) > 90:
        raise ToolError("Headline is too long for an image; keep it under 90 characters.")
    path = graphics.make_post_graphic(headline, subtext, platform.lower(), layout=layout, label=label,
                                      items=items, page=page)
    return to_json({"image_path": str(path.relative_to(ROOT)), "layout": layout,
                    "note": "Local file: fine for review and Canva upload. Instagram publishing needs a public "
                            "URL (export it through the Canva connector)."})


if __name__ == "__main__":
    mcp.run()
