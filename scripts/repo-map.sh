#!/usr/bin/env bash
# Generate a compressed repo map: file tree + exported symbols.
# Run from repo root: ./scripts/repo-map.sh > REPO_MAP.txt
#
# This is a quick-and-dirty alternative to tree-sitter-based tools.
# Output is meant for LLM consumption — compact, greppable, no noise.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "# Repo Map — generated $(date -I)"
echo "# $(git log -1 --format='%h %s' 2>/dev/null || echo 'no git history')"
echo ""

# --- File tree (source files only, no node_modules/dist/data) ---
echo "## File Tree"
echo ""
find backend/src frontend/src \
  -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" \) \
  ! -path "*/node_modules/*" ! -path "*/dist/*" ! -path "*/__pycache__/*" \
  | sort \
  | sed 's|^|  |'
echo ""

# --- Backend: Python classes, functions, routes ---
echo "## Backend Symbols"
echo ""
find backend/src -name "*.py" ! -path "*/__pycache__/*" | sort | while read -r f; do
  symbols=$(grep -nE '^\s*(class |def |async def |router\.(get|post|put|patch|delete)\()' "$f" 2>/dev/null | head -40 || true)
  if [ -n "$symbols" ]; then
    echo "### $f"
    echo "$symbols" | sed 's/^/  /'
    echo ""
  fi
done

# --- Frontend: exported components, functions, interfaces, types ---
echo "## Frontend Symbols"
echo ""
find frontend/src -name "*.ts" -o -name "*.tsx" | sort | while read -r f; do
  symbols=$(grep -nE '^\s*export\s+(default\s+)?(function|const|interface|type|class|enum)\s+' "$f" 2>/dev/null | head -40 || true)
  if [ -n "$symbols" ]; then
    echo "### $f"
    echo "$symbols" | sed 's/^/  /'
    echo ""
  fi
done
