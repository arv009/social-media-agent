"""Designer connector: makes on-brand post images locally (no Canva account needed).

Uses brand.json for colors, fonts, logo and voice. Images are saved to data/exports/.
"""
from _common import ROOT, to_json
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from social_agent import graphics

mcp = MCPServer("designer")


@mcp.tool()
def brand_guidelines() -> str:
    """The brand's name, handle, colors and writing voice. Read this before writing or designing."""
    return to_json(graphics.load_brand())


@mcp.tool()
def make_post_graphic(headline: str, subtext: str = "", platform: str = "instagram", style: str = "bold") -> str:
    """Create a simple on-brand image for a post: a big headline, optional supporting line,
    brand name and handle. Returns the image path to pass as image_url when submitting the draft.

    Args:
        headline: Short and punchy, ideally under 10 words.
        subtext: Optional supporting sentence (under 25 words).
        platform: instagram (1080x1350), facebook or linkedin (1080x1080).
        style: bold (brand color background), light (white background) or accent (accent color background).
    """
    if len(headline) > 120:
        raise ToolError("Headline is too long for an image; keep it under 120 characters.")
    path = graphics.make_post_graphic(headline, subtext, platform.lower(), style)
    return to_json({"image_path": str(path.relative_to(ROOT)), "size": graphics.SIZES.get(platform.lower()),
                    "note": "Local file: fine for review and Canva upload. Instagram publishing needs a public "
                            "URL (export it through the Canva connector)."})


if __name__ == "__main__":
    mcp.run()
