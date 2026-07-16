"""
Confluence to Markdown Downloader

Downloads all pages from one or more Confluence Cloud spaces and saves them
as markdown files, preserving the page hierarchy as nested folders.

Usage:
    python download.py                  # Interactive - lists spaces and lets you pick
    python download.py --space DEV      # Download a specific space
    python download.py --all            # Download all spaces
"""

import os
import re
import sys
import time
import argparse
from pathlib import Path

import requests
from dotenv import load_dotenv
from markdownify import markdownify as md

load_dotenv()

CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "").rstrip("/")
CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL", "")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")
OUTPUT_DIR = Path("output")


def get_auth():
    """Return basic auth tuple."""
    if not CONFLUENCE_EMAIL or not CONFLUENCE_API_TOKEN:
        print("Error: CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN must be set in .env")
        sys.exit(1)
    return (CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)


def api_get(path, params=None, retries=3):
    """Make an authenticated GET request to the Confluence REST API."""
    url = f"{CONFLUENCE_URL}/wiki/rest/api/{path}"

    for attempt in range(retries):
        try:
            response = requests.get(url, auth=get_auth(), params=params or {}, timeout=30)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                print(f"  Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            return response.json()

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  Connection error, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    # Final retry after rate limits exhausted
    return api_get(path, params, retries=1)


def list_spaces():
    """Fetch all available spaces."""
    spaces = []
    start = 0
    limit = 25

    while True:
        data = api_get("space", {"start": start, "limit": limit})
        spaces.extend(data.get("results", []))

        if data.get("size", 0) < limit:
            break
        start += limit

    return spaces


def get_space(space_key):
    """Fetch a single space by key."""
    try:
        data = api_get(f"space/{space_key}")
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise


def get_pages_in_space(space_key):
    """Fetch all pages in a space."""
    pages = []
    start = 0
    limit = 25

    while True:
        data = api_get("space/{}/content/page".format(space_key), {
            "start": start,
            "limit": limit,
            "expand": "ancestors"
        })
        pages.extend(data.get("results", []))

        if data.get("size", 0) < limit:
            break
        start += limit

    return pages


def get_page_content(page_id):
    """Fetch full page content with body in storage format."""
    data = api_get("content/{}".format(page_id), {
        "expand": "body.storage,metadata.labels,version"
    })
    return data


def sanitize_filename(name):
    """Make a string safe for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Truncate to avoid filesystem limits
    if len(name) > 100:
        name = name[:100]
    return name


def build_page_tree(pages):
    """Build a tree structure from pages using ancestor info."""
    page_map = {p["id"]: p for p in pages}
    tree = {}

    for page in pages:
        ancestors = page.get("ancestors", [])
        # Build the path from ancestors
        path_parts = [sanitize_filename(a.get("title", "untitled")) for a in ancestors]
        path_parts.append(sanitize_filename(page["title"]))
        tree[page["id"]] = {
            "title": page["title"],
            "path": path_parts
        }

    return tree


def convert_to_markdown(html_content, title, url):
    """Convert HTML content to markdown with frontmatter."""
    if not html_content:
        return f"# {title}\n\n*No content*\n"

    markdown_body = md(
        html_content,
        heading_style="ATX",
        code_language_callback=lambda el: el.get("data-language", ""),
        strip=["script", "style"]
    )

    # Build the file content with YAML frontmatter
    result = "---\n"
    result += f'title: "{title}"\n'
    result += f'source: "{url}"\n'
    result += f'exported: "{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}"\n'
    result += "---\n\n"
    result += f"# {title}\n\n"
    result += markdown_body

    return result


def download_space(space_key, space_name):
    """Download all pages from a single space."""
    print(f"\nDownloading space: {space_name} ({space_key})")
    print("  Fetching page list...")

    pages = get_pages_in_space(space_key)
    print(f"  Found {len(pages)} pages")

    if not pages:
        return

    page_tree = build_page_tree(pages)
    space_dir = OUTPUT_DIR / sanitize_filename(space_key)

    downloaded = 0
    errors = 0

    for page in pages:
        page_info = page_tree.get(page["id"])
        if not page_info:
            continue

        try:
            # Fetch full content
            full_page = get_page_content(page["id"])
            html_content = full_page.get("body", {}).get("storage", {}).get("value", "")

            # Build the page URL
            page_url = f"{CONFLUENCE_URL}/wiki/spaces/{space_key}/pages/{page['id']}"

            # Convert to markdown
            markdown = convert_to_markdown(html_content, page_info["title"], page_url)

            # Create output path
            file_path = space_dir
            for part in page_info["path"][:-1]:
                file_path = file_path / part
            file_path = file_path / (page_info["path"][-1] + ".md")

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(markdown, encoding="utf-8")

            downloaded += 1
            print(f"  [{downloaded}/{len(pages)}] {page_info['title']}")

            # Small delay to be kind to the API
            time.sleep(0.5)

        except Exception as e:
            errors += 1
            print(f"  ERROR: {page_info['title']} - {e}")

    print(f"  Done: {downloaded} downloaded, {errors} errors")


def interactive_select(spaces):
    """Let the user pick spaces interactively."""
    print("\nAvailable spaces:")
    print("-" * 50)
    for i, space in enumerate(spaces, 1):
        print(f"  {i:3}. [{space['key']}] {space['name']}")
    print("-" * 50)
    print("  Enter space numbers (comma-separated), 'all', or 'q' to quit:")

    choice = input("  > ").strip()

    if choice.lower() == 'q':
        sys.exit(0)

    if choice.lower() == 'all':
        return spaces

    try:
        indices = [int(x.strip()) - 1 for x in choice.split(",")]
        return [spaces[i] for i in indices if 0 <= i < len(spaces)]
    except (ValueError, IndexError):
        print("  Invalid selection")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Download Confluence spaces as Markdown")
    parser.add_argument("--space", help="Space key to download (e.g. DEV)")
    parser.add_argument("--all", action="store_true", help="Download all spaces")
    parser.add_argument("--test", action="store_true", help="Test connectivity and list spaces")
    args = parser.parse_args()

    if not CONFLUENCE_URL:
        print("Error: CONFLUENCE_URL must be set in .env")
        sys.exit(1)

    print(f"Confluence: {CONFLUENCE_URL}")

    # Fetch spaces
    print("\nFetching available spaces...")
    try:
        spaces = list_spaces()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("ERROR: Authentication failed. Check your email and API token in .env")
        elif e.response.status_code == 403:
            print("ERROR: Access denied. Your token may not have permission to this site.")
        else:
            print(f"ERROR: {e}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {CONFLUENCE_URL}. Check the URL in .env")
        sys.exit(1)

    print(f"Found {len(spaces)} spaces")

    if args.test:
        print("\nConnectivity OK. Available spaces:")
        print("-" * 50)
        for space in spaces:
            print(f"  [{space['key']}] {space['name']}")
        if not spaces:
            print("  (none returned by list - try --space KEY to access directly)")
        print("-" * 50)
        print("\nRun without --test to download.")
        sys.exit(0)

    if not spaces and not args.space:
        print("No spaces found. Check your credentials and permissions.")
        sys.exit(1)

    print(f"Output: {OUTPUT_DIR.absolute()}")

    # Determine which spaces to download
    if args.space:
        selected = [s for s in spaces if s["key"].upper() == args.space.upper()]
        if not selected:
            # Try fetching the space directly - the list endpoint may not return it
            print(f"  Space '{args.space}' not in list, trying direct access...")
            space_data = get_space(args.space)
            if space_data:
                selected = [space_data]
            else:
                print(f"  Space '{args.space}' not found or not accessible")
                sys.exit(1)
    elif args.all:
        selected = spaces
    else:
        selected = interactive_select(spaces)

    if not selected:
        print("No spaces selected")
        sys.exit(1)

    # Download each selected space
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for space in selected:
        download_space(space["key"], space["name"])

    print(f"\nComplete. Output saved to: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    main()
