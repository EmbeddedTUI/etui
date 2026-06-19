#!/usr/bin/env bash
# Copyright (c) 2026 32bitmico LLC
# Script to trigger the release build workflow on GitHub using the gh CLI.

set -e

# Verify gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed."
    echo "Please install it: https://cli.github.com/"
    exit 1
fi

# Verify gh authentication status
if ! gh auth status &> /dev/null; then
    echo "Error: gh CLI is not authenticated."
    echo "Please run 'gh auth login' to authenticate."
    exit 1
fi

# Read the canonical version from pyproject.toml ([project] table).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYPROJECT="$SCRIPT_DIR/pyproject.toml"

get_pyproject_version() {
    [ -f "$PYPROJECT" ] || return 1
    awk '
        /^\[project\]/ { inproj=1; next }
        /^\[/          { inproj=0 }
        inproj && /^[[:space:]]*version[[:space:]]*=/ {
            gsub(/^[^"]*"/, ""); gsub(/".*$/, ""); print; exit
        }
    ' "$PYPROJECT"
}

PYPROJECT_VERSION=$(get_pyproject_version)
if [ -z "$PYPROJECT_VERSION" ]; then
    echo "Error: could not read version from $PYPROJECT"
    exit 1
fi
echo "Version from pyproject.toml: $PYPROJECT_VERSION"

BUMP=""
VERSION=""

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --bump-major) BUMP="major"; shift ;;
        --bump-minor) BUMP="minor"; shift ;;
        --bump-patch) BUMP="patch"; shift ;;
        v*) VERSION=$1; shift ;; # Accept direct version tag (e.g. v1.0.0)
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Resolve semantic versioning bump if requested, based on the pyproject version.
if [ -n "$BUMP" ]; then
    IFS='.' read -r MAJOR MINOR PATCH <<< "$PYPROJECT_VERSION"
    MAJOR=${MAJOR:-0}
    MINOR=${MINOR:-0}
    PATCH=${PATCH:-0}

    case $BUMP in
        major)
            MAJOR=$((MAJOR + 1))
            MINOR=0
            PATCH=0
            ;;
        minor)
            MINOR=$((MINOR + 1))
            PATCH=0
            ;;
        patch)
            PATCH=$((PATCH + 1))
            ;;
    esac
    VERSION="v$MAJOR.$MINOR.$PATCH"
    echo "Semantic bump ($BUMP) from pyproject $PYPROJECT_VERSION -> $VERSION"
fi

# Fallback to interactive prompt, defaulting to the pyproject.toml version.
if [ -z "$VERSION" ]; then
    SUGGESTED_TAG="v$PYPROJECT_VERSION"
    read -p "Enter version tag to release [default: $SUGGESTED_TAG]: " VERSION
    VERSION=$(echo "$VERSION" | xargs)
    if [ -z "$VERSION" ]; then
        VERSION="$SUGGESTED_TAG"
    fi
fi

# Basic formatting check (should start with 'v')
if [[ ! "$VERSION" =~ ^v[0-9] ]]; then
    echo "Warning: Version tag should ideally follow semver format (e.g., v0.1.0)"
    read -p "Are you sure you want to proceed with tag '$VERSION'? (y/N): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 1
    fi
fi

# Push local changes to ensure the remote repository is in sync
echo "Pushing local commits to remote repository..."
git push

# Trigger the GitHub Actions workflow via dispatch
echo "Triggering GitHub Actions release workflow 'Package etui Release' for tag '$VERSION'..."
if ! gh workflow run package.yml -f version="$VERSION"; then
    echo ""
    echo "Error: Failed to trigger workflow."
    echo "This can happen if:"
    echo "  1. The workflow file '.github/workflows/package.yml' is not pushed to the remote repository yet."
    echo "  2. You do not have write/push permissions for this repository."
    echo "Please ensure you have pushed your latest local changes (git push) and retry."
    exit 1
fi

# Wait a moment for the run to register
sleep 3

# Fetch the active workflow run to watch
echo "Watching active run on GitHub..."
RUN_ID=$(gh run list --workflow=package.yml --limit 1 --json databaseId --jq '.[0].databaseId')

if [ -n "$RUN_ID" ]; then
    # Disable immediate exit on error to capture watch exit code
    set +e
    gh run watch "$RUN_ID"
    EXIT_CODE=$?
    set -e

    if [ "$EXIT_CODE" -ne 0 ]; then
        echo ""
        echo "========================================================================"
        echo "ERROR: GitHub Actions workflow run failed!"
        echo "Retrieving detailed logs for failed steps..."
        echo "========================================================================"
        gh run view "$RUN_ID" --log-failed
        exit "$EXIT_CODE"
    else
        echo "Workflow completed successfully!"
    fi
else
    echo "Workflow started, but could not retrieve run ID. Check status online: gh run list --workflow=package.yml"
fi
