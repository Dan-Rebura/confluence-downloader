"""
Confluence Downloader MCP Server

Exposes confluence download functionality as MCP tools.
Credentials (CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN) are loaded from .env.
CONFLUENCE_URL can be overridden per tool call for multi-org access.
"""

import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from the same directory as this script
_script_dir = Path(__file__).parent
load_dotenv(_script_dir / ".env")

CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL", "")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
DEFAULT_CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "").rstrip("/")
DEFAULT_OUTPUT_DIR = "confluence-export"


def _resolve_output_dir(output_dir: str | None) -> Path:
    """Resolve the output directory. Defaults to ./confluence-export relative to cwd."""
    if output_dir:
        return Path(output_dir).resolve()
    return Path.cwd() / DEFAULT_OUTPUT_DIR

mcp = FastMCP(
    "confluence-downloader",
    instructions="Download pages from Confluence Cloud as Markdown with images"
)


def _get_auth():
    """Return basic auth tuple."""
    if not CONFLUENCE_EMAIL or not CONFLUENCE_API_TOKEN:
        raise ValueError("CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN must be set in .env")
    return (CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)


def _resolve_url(confluence_url: str | None) -> str:
    """Resolve the Confluence base URL, using the provided value or falling back to .env."""
    url = (confluence_url or DEFAULT_CONFLUENCE_URL).rstrip("/")
    if not url:
        raise ValueError(
            "No Confluence URL provided and CONFLUENCE_URL is not set in .env. "
            "Pass confluence_url parameter or set CONFLUENCE_URL in .env."
        )
    return url


def _api_get(base_url: str, path: str, params: dict | None = None, retries: int = 3):
    """Make an authenticated GET request to the Confluence REST API."""
    url = f"{base_url}/wiki/rest/api/{path}"

    for attempt in range(retries):
        try:
            response = requests.get(url, auth=_get_auth(), params=params or {}, timeout=30)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            return response.json()

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
            else:
                raise

    return _api_get(base_url, path, params, retries=1)


def _sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 100:
        name = name[:100]
    return name


def _download_image(base_url: str, url: str, dest_path: Path, retries: int = 3) -> bool:
    """Download an image file from Confluence."""
    for attempt in range(retries):
        try:
            response = requests.get(url, auth=_get_auth(), timeout=30, stream=True)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue

            if response.status_code != 200:
                return False

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
            else:
                return False

    return False


def _extract_and_download_images(base_url: str, html_content: str, page_dir: Path, page_id: str | None = None) -> dict:
    """Find all images in HTML, download them, return URL-to-local-path mapping."""
    if not html_content:
        return {}

    img_patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<ri:url[^>]+ri:value=["\']([^"\']+)["\']',
    ]

    urls = set()
    for pattern in img_patterns:
        urls.update(re.findall(pattern, html_content))

    attachment_pattern = r'<ri:attachment\s+ri:filename=["\']([^"\']+)["\']'
    attachment_filenames = re.findall(attachment_pattern, html_content)

    url_mapping = {}
    images_dir = page_dir / "images"
    img_count = 0

    for url in urls:
        if url.startswith("data:") or "/emoticons/" in url or "/icons/" in url:
            continue

        if url.startswith("/"):
            full_url = f"{base_url}{url}"
        elif not url.startswith("http"):
            continue
        else:
            full_url = url

        parsed = urlparse(full_url)
        filename = unquote(parsed.path.split("/")[-1])
        if not filename or filename == "download":
            img_count += 1
            filename = f"image_{img_count}.png"

        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

        dest = images_dir / filename
        if _download_image(base_url, full_url, dest):
            url_mapping[url] = f"images/{filename}"

    if attachment_filenames and page_id:
        for att_filename in attachment_filenames:
            try:
                att_data = _api_get(base_url, f"content/{page_id}/child/attachment", {"filename": att_filename})
                results = att_data.get("results", [])
                if results:
                    download_link = results[0].get("_links", {}).get("download", "")
                    if download_link:
                        full_url = f"{base_url}/wiki{download_link}"
                        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', att_filename)
                        safe_filename = safe_filename.replace(' ', '-')
                        dest = images_dir / safe_filename
                        if _download_image(base_url, full_url, dest):
                            url_mapping[att_filename] = f"images/{safe_filename}"
            except Exception:
                pass

    return url_mapping


def _preprocess_confluence_html(html_content: str, image_mapping: dict) -> str:
    """Convert Confluence-specific XML tags to standard HTML."""
    if not html_content:
        return html_content

    def replace_ac_image(match):
        block = match.group(0)
        att_match = re.search(r'<ri:attachment\s+ri:filename=["\']([^"\']+)["\']', block)
        if att_match:
            filename = att_match.group(1)
            src = image_mapping.get(filename, filename)
            alt = filename.rsplit('.', 1)[0]
            return f'<img src="{src}" alt="{alt}" />'
        url_match = re.search(r'<ri:url\s+ri:value=["\']([^"\']+)["\']', block)
        if url_match:
            url = url_match.group(1)
            src = image_mapping.get(url, url)
            return f'<img src="{src}" alt="" />'
        return ''

    html_content = re.sub(r'<ac:image[^>]*>.*?</ac:image>', replace_ac_image, html_content, flags=re.DOTALL)
    return html_content


def _convert_to_markdown(html_content: str, title: str, url: str, image_mapping: dict | None = None) -> str:
    """Convert HTML content to markdown with frontmatter."""
    from markdownify import markdownify as md_convert

    if not html_content:
        return f"# {title}\n\n*No content*\n"

    if image_mapping is None:
        image_mapping = {}

    html_content = _preprocess_confluence_html(html_content, image_mapping)

    markdown_body = md_convert(
        html_content,
        heading_style="ATX",
        code_language_callback=lambda el: el.get("data-language", ""),
        strip=["script", "style"]
    )

    result = "---\n"
    result += f'title: "{title}"\n'
    result += f'source: "{url}"\n'
    result += f'exported: "{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}"\n'
    result += "---\n\n"
    result += f"# {title}\n\n"
    result += markdown_body

    return result


def _extract_page_id(page_ref: str) -> str | None:
    """Extract a page ID from a URL or return the ID if numeric."""
    if page_ref.startswith("http"):
        match = re.search(r'/pages/(\d+)', page_ref)
        if match:
            return match.group(1)
        match = re.search(r'pageId=(\d+)', page_ref)
        if match:
            return match.group(1)
    elif page_ref.isdigit():
        return page_ref
    return None


# --- MCP Tools ---


@mcp.tool()
def test_connection(confluence_url: str | None = None) -> str:
    """
    Test connectivity to Confluence and list available spaces.

    Args:
        confluence_url: Confluence base URL (e.g. https://yoursite.atlassian.net). 
                       Falls back to CONFLUENCE_URL in .env if not provided.
    """
    base_url = _resolve_url(confluence_url)

    try:
        spaces = []
        start = 0
        limit = 25

        while True:
            data = _api_get(base_url, "space", {"start": start, "limit": limit})
            spaces.extend(data.get("results", []))
            if data.get("size", 0) < limit:
                break
            start += limit

        lines = [f"Connected to: {base_url}", f"Found {len(spaces)} spaces:", ""]
        for space in spaces:
            lines.append(f"  [{space['key']}] {space['name']}")

        if not spaces:
            lines.append("  (none returned - you may still access spaces directly by key)")

        return "\n".join(lines)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return f"Authentication failed for {base_url}. Check email and API token in .env."
        elif e.response.status_code == 403:
            return f"Access denied to {base_url}. Token may lack permissions."
        else:
            return f"HTTP error: {e}"
    except requests.exceptions.ConnectionError:
        return f"Could not connect to {base_url}. Check the URL."


@mcp.tool()
def list_spaces(confluence_url: str | None = None) -> str:
    """
    List all available Confluence spaces.

    Args:
        confluence_url: Confluence base URL. Falls back to CONFLUENCE_URL in .env if not provided.
    """
    base_url = _resolve_url(confluence_url)

    spaces = []
    start = 0
    limit = 25

    while True:
        data = _api_get(base_url, "space", {"start": start, "limit": limit})
        spaces.extend(data.get("results", []))
        if data.get("size", 0) < limit:
            break
        start += limit

    if not spaces:
        return "No spaces found. Check credentials and permissions."

    lines = [f"Found {len(spaces)} spaces on {base_url}:", ""]
    for space in spaces:
        lines.append(f"  [{space['key']}] {space['name']}")

    return "\n".join(lines)


@mcp.tool()
def download_space(space_key: str, confluence_url: str | None = None, output_dir: str | None = None) -> str:
    """
    Download all pages from a Confluence space as Markdown files.

    Pages are saved preserving the hierarchy as nested folders.
    Images are downloaded locally.

    Args:
        space_key: The space key (e.g. CTM, DEV).
        confluence_url: Confluence base URL. Falls back to CONFLUENCE_URL in .env if not provided.
        output_dir: Directory to save files to. Defaults to ./confluence-export in the current workspace.
    """
    base_url = _resolve_url(confluence_url)
    out_dir = _resolve_output_dir(output_dir)

    # Fetch all pages in the space
    pages = []
    start = 0
    limit = 25

    while True:
        data = _api_get(base_url, f"space/{space_key}/content/page", {
            "start": start,
            "limit": limit,
            "expand": "ancestors"
        })
        pages.extend(data.get("results", []))
        if data.get("size", 0) < limit:
            break
        start += limit

    if not pages:
        return f"No pages found in space '{space_key}'. Check the space key exists and you have access."

    # Build page tree
    tree = {}
    for page in pages:
        ancestors = page.get("ancestors", [])
        path_parts = [_sanitize_filename(a.get("title", "untitled")) for a in ancestors]
        path_parts.append(_sanitize_filename(page["title"]))
        tree[page["id"]] = {"title": page["title"], "path": path_parts}

    space_dir = out_dir / _sanitize_filename(space_key)
    space_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    errors = 0
    error_details = []

    for page in pages:
        page_info = tree.get(page["id"])
        if not page_info:
            continue

        try:
            full_page = _api_get(base_url, f"content/{page['id']}", {
                "expand": "body.storage,metadata.labels,version"
            })
            html_content = full_page.get("body", {}).get("storage", {}).get("value", "")
            page_url = f"{base_url}/wiki/spaces/{space_key}/pages/{page['id']}"

            file_path = space_dir
            for part in page_info["path"][:-1]:
                file_path = file_path / part
            file_path = file_path / (page_info["path"][-1] + ".md")
            file_path.parent.mkdir(parents=True, exist_ok=True)

            image_mapping = _extract_and_download_images(base_url, html_content, file_path.parent, page_id=page["id"])
            markdown = _convert_to_markdown(html_content, page_info["title"], page_url, image_mapping)
            file_path.write_text(markdown, encoding="utf-8")

            downloaded += 1
            time.sleep(0.5)

        except Exception as e:
            errors += 1
            error_details.append(f"  {page_info['title']}: {e}")

    lines = [
        f"Space '{space_key}' download complete.",
        f"  Pages downloaded: {downloaded}",
        f"  Errors: {errors}",
        f"  Output: {space_dir.absolute()}"
    ]
    if error_details:
        lines.append("")
        lines.append("Errors:")
        lines.extend(error_details[:10])
        if len(error_details) > 10:
            lines.append(f"  ... and {len(error_details) - 10} more")

    return "\n".join(lines)


@mcp.tool()
def download_page(page_ref: str, confluence_url: str | None = None, output_dir: str | None = None, raw: bool = False) -> str:
    """
    Download a single Confluence page as Markdown.

    Args:
        page_ref: Page URL (containing /pages/<ID>) or numeric page ID.
        confluence_url: Confluence base URL. Falls back to CONFLUENCE_URL in .env if not provided.
        output_dir: Directory to save files to. Defaults to ./confluence-export in the current workspace.
        raw: If True, save raw HTML storage format instead of Markdown (for debugging).
    """
    base_url = _resolve_url(confluence_url)
    out_dir = _resolve_output_dir(output_dir)
    page_id = _extract_page_id(page_ref)

    if not page_id:
        return f"Could not extract page ID from '{page_ref}'. Provide a page URL (containing /pages/ID) or a numeric page ID."

    try:
        full_page = _api_get(base_url, f"content/{page_id}", {
            "expand": "body.storage,metadata.labels,version"
        })
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"Page {page_id} not found."
        return f"Error fetching page: {e}"

    title = full_page.get("title", "Untitled")
    html_content = full_page.get("body", {}).get("storage", {}).get("value", "")
    page_url = f"{base_url}/wiki/pages/{page_id}"

    out_dir.mkdir(parents=True, exist_ok=True)

    if raw:
        raw_path = out_dir / (_sanitize_filename(title) + ".html")
        raw_path.write_text(html_content, encoding="utf-8")
        return f"Raw HTML saved: {raw_path.absolute()}"

    filename = _sanitize_filename(title) + ".md"
    file_path = out_dir / filename

    image_mapping = _extract_and_download_images(base_url, html_content, file_path.parent, page_id=page_id)
    markdown = _convert_to_markdown(html_content, title, page_url, image_mapping)
    file_path.write_text(markdown, encoding="utf-8")

    img_note = f" (+{len(image_mapping)} images)" if image_mapping else ""
    return f"Downloaded: {title}{img_note}\nSaved to: {file_path.absolute()}"


@mcp.tool()
def download_page_tree(page_ref: str, confluence_url: str | None = None, output_dir: str | None = None) -> str:
    """
    Download a page and all its descendant pages recursively as Markdown.

    Args:
        page_ref: Page URL (containing /pages/<ID>) or numeric page ID for the root page.
        confluence_url: Confluence base URL. Falls back to CONFLUENCE_URL in .env if not provided.
        output_dir: Directory to save files to. Defaults to ./confluence-export in the current workspace.
    """
    base_url = _resolve_url(confluence_url)
    out_dir = _resolve_output_dir(output_dir)
    page_id = _extract_page_id(page_ref)

    if not page_id:
        return f"Could not extract page ID from '{page_ref}'. Provide a page URL (containing /pages/ID) or a numeric page ID."

    try:
        root_page = _api_get(base_url, f"content/{page_id}", {
            "expand": "body.storage,metadata.labels,version"
        })
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return f"Page {page_id} not found."
        return f"Error fetching page: {e}"

    root_title = root_page.get("title", "Untitled")

    # Recursively fetch all descendants
    def get_all_descendants(pid):
        descendants = []
        start = 0
        limit = 25
        while True:
            data = _api_get(base_url, f"content/{pid}/child/page", {"start": start, "limit": limit})
            children = data.get("results", [])
            descendants.extend(children)
            for child in children:
                descendants.extend(get_all_descendants(child["id"]))
            if data.get("size", 0) < limit:
                break
            start += limit
        return descendants

    descendants = get_all_descendants(page_id)
    all_pages = [root_page] + descendants

    tree_dir = out_dir / _sanitize_filename(root_title)
    tree_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    errors = 0
    error_details = []

    for page in all_pages:
        pid = page["id"]
        title = page.get("title", "Untitled")

        try:
            if "body" not in page:
                page = _api_get(base_url, f"content/{pid}", {
                    "expand": "body.storage,metadata.labels,version"
                })

            html_content = page.get("body", {}).get("storage", {}).get("value", "")
            page_url = f"{base_url}/wiki/pages/{pid}"

            if pid == page_id:
                file_path = tree_dir / (_sanitize_filename(title) + ".md")
            else:
                full_page_data = _api_get(base_url, f"content/{pid}", {"expand": "ancestors"})
                ancestors = full_page_data.get("ancestors", [])

                path_parts = []
                found_root = False
                for ancestor in ancestors:
                    if ancestor["id"] == page_id:
                        found_root = True
                        continue
                    if found_root:
                        path_parts.append(_sanitize_filename(ancestor.get("title", "untitled")))

                path_parts.append(_sanitize_filename(title))

                file_path = tree_dir
                for part in path_parts[:-1]:
                    file_path = file_path / part
                file_path = file_path / (path_parts[-1] + ".md")

            file_path.parent.mkdir(parents=True, exist_ok=True)

            image_mapping = _extract_and_download_images(base_url, html_content, file_path.parent, page_id=pid)
            markdown = _convert_to_markdown(html_content, title, page_url, image_mapping)
            file_path.write_text(markdown, encoding="utf-8")

            downloaded += 1
            time.sleep(0.5)

        except Exception as e:
            errors += 1
            error_details.append(f"  {title}: {e}")

    lines = [
        f"Page tree download complete.",
        f"  Root: {root_title}",
        f"  Pages downloaded: {downloaded} (1 root + {len(descendants)} descendants)",
        f"  Errors: {errors}",
        f"  Output: {tree_dir.absolute()}"
    ]
    if error_details:
        lines.append("")
        lines.append("Errors:")
        lines.extend(error_details[:10])
        if len(error_details) > 10:
            lines.append(f"  ... and {len(error_details) - 10} more")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
