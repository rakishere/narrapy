# Runs narrapy from this source folder with the project's .venv - no activation needed.
# One-time setup: uv pip install --python .venv\Scripts\python.exe -e .
# Usage: .\run.ps1 "book.pdf" --preview
#        .\run.ps1 voices --group best
#        .\run.ps1 --help
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m narrapy @args
exit $LASTEXITCODE
