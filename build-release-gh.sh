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

# Retrieve version argument
VERSION=$1
if [ -z "$VERSION" ]; then
    read -p "Enter version tag to release (e.g., v0.1.0): " VERSION
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

# Trigger the GitHub Actions workflow via dispatch
echo "Triggering GitHub Actions release workflow 'Package etui Release' for tag '$VERSION'..."
gh workflow run package.yml -f version="$VERSION"

# Wait a moment for the run to register
sleep 3

# Fetch the active workflow run to watch
echo "Watching active run on GitHub..."
RUN_ID=$(gh run list --workflow=package.yml --limit 1 --json databaseId --jq '.[0].databaseId')

if [ -n "$RUN_ID" ]; then
    gh run watch "$RUN_ID"
else
    echo "Workflow started, but could not retrieve run ID. Check status online: gh run list --workflow=package.yml"
fi
