# Confluence Downloader

Downloads all pages from a Confluence Cloud space and saves them as Markdown files, preserving the page hierarchy as nested folders.

## Setup

1. Install dependencies:

```
pip install -r requirements.txt
```

2. Copy `.env` and fill in your credentials:

```
CONFLUENCE_URL=https://your-site.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-token
```

Generate an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

## Usage

Test connectivity:

```
python download.py --test
```

Download a specific space:

```
python download.py --space CTM
```

Download all spaces:

```
python download.py --all
```

Interactive mode (lists spaces and lets you pick):

```
python download.py
```

## Output

Files are saved to `output/<SPACE_KEY>/` with the page tree mirrored as folders:

```
output/
  CTM/
    Getting Started.md
    Architecture/
      Overview.md
      Networking.md
```

Each file includes YAML frontmatter with the title, source URL and export timestamp.

## Notes

- The script adds a 0.5s delay between API calls and retries automatically on connection resets.
- Large spaces may take a few minutes depending on page count.
- The `output/` folder is gitignored.
