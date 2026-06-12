# Files Tab

Browse and preview the files in your workspace.


## Layout

| Area | Description |
|------|-------------|
| Top bar | Workspace root path input and **Open** button |
| Left pane (30%) | Directory tree rooted at the workspace folder |
| Right pane (70%) | File viewer with **Content** / **Details** toggle |

## Usage

1. Enter a path in the workspace root field and press **Open**, or set the workspace root in **Settings → Workspace**.
2. Navigate the directory tree with the arrow keys or mouse.
3. Select a file to preview it on the right.
   - **Content** — syntax-highlighted source code.
   - **Details** — file size, MIME type, and modification time.

## Notes

- The workspace root is shared across tabs. Changing it in Files also updates Git, GitHub, CMake, and Console.
- Binary files show metadata only; text files are highlighted using Pygments.
