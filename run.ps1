# run.ps1 - part of narrapy (https://github.com/rakishere/narrapy)
# Author: Rakesh Sharma
# Copyright (c) 2026 Rakesh Sharma
# Licensed under the MIT License. See the LICENSE file for details.
# SPDX-License-Identifier: MIT

# Runs narrapy from this source folder with the project's .venv - no activation needed.
# One-time setup: uv pip install --python .venv\Scripts\python.exe -e .
# Usage: .\run.ps1 "book.pdf" --preview
#        .\run.ps1 voices --group best
#        .\run.ps1 --help
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m narrapy @args
exit $LASTEXITCODE
