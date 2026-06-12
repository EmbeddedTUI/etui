# GitHub Tab

Browse issues and pull requests for the GitHub repository associated with your workspace, powered by the `gh` CLI.


## Layout

| Area | Description |
|------|-------------|
| Navigation bar | **Issues** / **PRs** toggle and **Refresh** button |
| Left pane (40%) | Paginated list of issues or pull requests |
| Right pane (60%) | Detail view — body, labels, assignees, comments |
| Action bar | Contextual actions: **Open in browser**, **Checkout PR branch** |

## Prerequisites

- `gh` CLI must be installed and authenticated (`gh auth login`).
- The workspace must be inside a Git repository with a GitHub remote.

## Usage

1. Switch between **Issues** and **Pull Requests** using the navigation buttons.
2. Select an item to read its full description and comments.
3. Use **Open in browser** to continue in GitHub.
4. On a PR row, **Checkout PR branch** fetches and checks out the branch locally.

## Notes

- Items are fetched in pages of 50. Scroll to the bottom of the list to load more.
- Only repositories hosted on `github.com` are supported (not GitHub Enterprise at custom domains).
