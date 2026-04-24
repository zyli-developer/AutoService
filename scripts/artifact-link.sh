#!/bin/bash
set -euo pipefail

# 建立两个 artifact 之间的双向关联。

DRY_RUN=false
PROJECT_ROOT=""
FROM_ID=""
TO_ID=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --project-root <path> --from <id> --to <id>
       [--dry-run] [--help]

Create a bidirectional link between two artifacts.

Options:
  --project-root <path>  Project root directory (required)
  --from <id>            Source artifact ID (required)
  --to <id>              Target artifact ID (required)
  --dry-run              Show what would be done without making changes
  --help                 Show this help message

Both artifacts' related_ids fields are updated. Duplicate links are ignored.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --from) FROM_ID="$2"; shift 2 ;;
        --to) TO_ID="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage ;;
        *) echo "Error: unknown option '$1'. Use --help for usage." >&2; exit 1 ;;
    esac
done

for param in PROJECT_ROOT FROM_ID TO_ID; do
    if [[ -z "${!param}" ]]; then
        echo "Error: --$(echo "$param" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required." >&2
        exit 1
    fi
done

REGISTRY="$PROJECT_ROOT/.artifacts/registry.json"
if [[ ! -f "$REGISTRY" ]]; then
    echo "Error: registry not found at $REGISTRY." >&2
    exit 1
fi

if [[ "$FROM_ID" == "$TO_ID" ]]; then
    echo "Error: cannot link an artifact to itself." >&2
    exit 1
fi

if $DRY_RUN; then
    echo "[dry-run] Would link '$FROM_ID' <-> '$TO_ID'"
    echo "[dry-run] Would update $REGISTRY"
    echo "[dry-run] Would run: git add .artifacts/ && git commit"
    exit 0
fi

python3 -c "
import json, sys

with open('$REGISTRY', encoding='utf-8') as f:
    data = json.load(f)

from_id = '$FROM_ID'
to_id = '$TO_ID'

ids = {a['id'] for a in data['artifacts']}
if from_id not in ids:
    print(f'Error: artifact \"{from_id}\" not found.', file=sys.stderr)
    sys.exit(1)
if to_id not in ids:
    print(f'Error: artifact \"{to_id}\" not found.', file=sys.stderr)
    sys.exit(1)

for a in data['artifacts']:
    if a['id'] == from_id and to_id not in a.get('related_ids', []):
        a.setdefault('related_ids', []).append(to_id)
    if a['id'] == to_id and from_id not in a.get('related_ids', []):
        a.setdefault('related_ids', []).append(from_id)

with open('$REGISTRY', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
"

cd "$PROJECT_ROOT"
git add .artifacts/
git commit -m "artifact: link $FROM_ID <-> $TO_ID"

echo "Linked $FROM_ID <-> $TO_ID"
