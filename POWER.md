---
name: "confluence-downloader"
displayName: "Confluence Downloader"
description: "Download pages from Confluence Cloud as Markdown with images. Supports single pages, page trees and full spaces with folder hierarchy preserved."
keywords: ["confluence", "atlassian", "download", "markdown", "wiki", "export", "documentation"]
author: "Daniel Shone"
---

# Confluence Downloader

## Overview

Download pages from Confluence Cloud and save them as Markdown files with images stored locally. Supports multiple Confluence orgs by passing `confluence_url` per request, falling back to a default configured in `.env`.

## Available MCP Servers

This power provides one MCP server: `confluence-downloader`

### Tools

| Tool | Description |
|------|-------------|
| `test_connection` | Verify credentials and list available spaces |
| `list_spaces` | List all accessible Confluence spaces |
| `download_space` | Download all pages in a space with folder hierarchy |
| `download_page` | Download a single page by URL or ID |
| `download_page_tree` | Download a page and all its descendants recursively |

## Onboarding

### Prerequisites

- Python 3.10+
- Dependencies installed: `pip install -r requirements.txt` from the power's directory

### Credential Setup

Create a `.env` file in the power's root directory:

```
CONFLUENCE_URL=https://your-site.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-token
```

- `CONFLUENCE_URL` - default Atlassian site (can be overridden per tool call)
- `CONFLUENCE_EMAIL` - your Atlassian login email
- `CONFLUENCE_API_TOKEN` - unscoped API token

Generate tokens at: https://id.atlassian.com/manage-profile/security/api-tokens

**Important:** The token must be unscoped. Scoped tokens return 403 on the classic REST API endpoints.

## Tool Usage Examples

### Test connectivity

Ask: "Test my Confluence connection"

The agent calls `test_connection` and reports available spaces.

### Download a space

Ask: "Download the CTM space from Confluence"

The agent calls `download_space` with `space_key="CTM"`. Output goes to `output/CTM/`.

### Download from a different org

Ask: "Download the DEV space from https://otherclient.atlassian.net"

The agent calls `download_space` with `space_key="DEV"` and `confluence_url="https://otherclient.atlassian.net"`.

### Download a single page

Ask: "Download this Confluence page: https://yoursite.atlassian.net/wiki/spaces/CTM/pages/123456"

The agent calls `download_page` with the URL. It extracts the page ID automatically.

### Download a page tree

Ask: "Download the Architecture page and everything beneath it from Confluence"

The agent calls `download_page_tree` with the page URL or ID.

### Debug with raw HTML

Ask: "Download page 123456 as raw HTML"

The agent calls `download_page` with `raw=True` to get the Confluence storage format.

## Output Format

- Files saved to `./confluence-export/` in the current workspace by default
- Pass `output_dir` to any download tool to save elsewhere
- Each Markdown file includes YAML frontmatter: title, source URL, export timestamp
- Images are downloaded to an `images/` subfolder next to each page
- Spaces in image filenames are replaced with hyphens

## Behaviour

- 0.5s delay between API calls to avoid throttling
- Retry with exponential backoff on connection resets
- Handles HTTP 429 rate limiting with Retry-After header
- Confluence XML (`ac:image`, `ri:attachment`) is preprocessed into standard HTML before conversion

## Troubleshooting

### Authentication failed (401)

Check `CONFLUENCE_EMAIL` and `CONFLUENCE_API_TOKEN` in `.env`. The token must be generated for the same email address.

### Access denied (403)

The API token is likely scoped. Generate an unscoped token instead. Scoped tokens do not work with the classic REST API.

### Space not found

The space key is case-sensitive. Use `test_connection` or `list_spaces` to see available spaces. Some spaces may not appear in the list but can still be accessed directly by key.

### Connection errors

Check `CONFLUENCE_URL` is correct and accessible. The script retries with exponential backoff on connection resets.
