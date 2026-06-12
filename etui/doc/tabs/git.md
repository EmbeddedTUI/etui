# Git Tab

A visual Git dashboard for staging, reviewing diffs, and committing changes.


## Layout

| Area | Description |
|------|-------------|
| Repo bar | Repository path selector |
| Info bar | Current branch and HEAD commit summary |
| Left pane (35%) | Changed-files tree, grouped by staged / unstaged |
| Right pane — diff viewer (65%) | Unified diff of the selected file |
| Action bar | Commit message input, **Stage**, **Unstage**, **Commit** buttons |

## Usage

1. The repository is set automatically from the workspace root. Switch it with the repo path input.
2. Select a file in the tree to view its diff.
3. Click **Stage** to add the file to the index, or **Unstage** to remove it.
4. Type a commit message and click **Commit**.

## Notes

- Diffs larger than 100 KB are truncated to protect terminal performance.
- The tab refreshes automatically when the workspace root changes.
- Merge commits and binary files show metadata rather than a diff.
