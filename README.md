# Confluence Downloader

A Kiro Power and MCP server for downloading Confluence Cloud pages as Markdown with images.

## Features

- Download entire spaces with folder hierarchy preserved
- Download single pages or page trees (page + all descendants)
- Images downloaded locally with markdown-compatible references
- Multi-org support (override Confluence URL per request)
- YAML frontmatter on each page (title, source URL, export timestamp)
- Rate limiting, retry logic and exponential backoff

## Install as a Kiro Power

In Kiro, open the Powers panel and use "Add Custom Power" → "Import from GitHub" with this repo URL.

After installing, configure your credentials in the Power's MCP settings:

| Variable | Description |
|----------|-------------|
| `CONFLUENCE_URL` | Default Atlassian site URL (can be overridden per request) |
| `CONFLUENCE_EMAIL` | Your Atlassian login email |
| `CONFLUENCE_API_TOKEN` | Unscoped API token |

Generate tokens at [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens). The token must be **unscoped**; scoped tokens return 403 on the classic REST API.

## Install standalone

```bash
pip install confluence-downloader-mcp
```

Or run directly with uvx:

```bash
uvx confluence-downloader-mcp
```

## Available tools

| Tool | Description |
|------|-------------|
| `test_connection` | Verify credentials and list spaces |
| `list_spaces` | List all accessible spaces |
| `download_space` | Download all pages in a space |
| `download_page` | Download a single page by URL or ID |
| `download_page_tree` | Download a page and all descendants |

## MCP configuration

Add to your MCP config (e.g. `~/.kiro/settings/mcp.json`):

```json
{
  "mcpServers": {
    "confluence-downloader": {
      "command": "uvx",
      "args": ["confluence-downloader-mcp"],
      "env": {
        "CONFLUENCE_URL": "https://your-site.atlassian.net",
        "CONFLUENCE_EMAIL": "you@example.com",
        "CONFLUENCE_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

## Output

Files are saved to `./confluence-export/` in the current workspace by default. Pass `output_dir` to any download tool to save elsewhere.

## License

MIT
