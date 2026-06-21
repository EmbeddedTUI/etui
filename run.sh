#!/usr/bin/env bash
set -euo pipefail

pdm install -G default-tabs
pdm run etui
