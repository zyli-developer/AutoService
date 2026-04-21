#!/bin/bash
set -euo pipefail

# 注册新 artifact 到 registry.json。
# 生成唯一 ID，写入索引，git commit。

DRY_RUN=false
PROJECT_ROOT=""
TYPE=""
NAME=""
PRODUCER=""
ARTIFACT_PATH=""
STATUS="draft"
RELATED=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --project-root <path> --type <type> --name <name> \\
       --producer <producer> --path <path> [--status <status>] [--related <ids>] \\
       [--dry-run] [--help]

Register a new artifact in the registry.

Required:
  --project-root <path>   Project root directory
  --type <type>           Artifact type: eval-doc|code-diff|test-plan|test-diff|
                          e2e-report|issue|coverage-matrix
  --name <name>           Human-readable name
  --producer <producer>   Producing skill (e.g. skill-5, phase-2)
  --path <path>           Relative path from project root

Optional:
  --status <status>       Initial status (default: draft)
  --related <ids>         Comma-separated related artifact IDs
  --dry-run               Show what would be done without making changes
  --help                  Show this help message

Output: prints the generated artifact ID to stdout.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --type) TYPE="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --producer) PRODUCER="$2"; shift 2 ;;
        --path) ARTIFACT_PATH="$2"; shift 2 ;;
        --status) STATUS="$2"; shift 2 ;;
        --related) RELATED="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage ;;
        *) echo "Error: unknown option '$1'. Use --help for usage." >&2; exit 1 ;;
    esac
done

# 参数验证
for param in PROJECT_ROOT TYPE NAME PRODUCER ARTIFACT_PATH; do
    if [[ -z "${!param}" ]]; then
        echo "Error: --$(echo "$param" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required." >&2
        exit 1
    fi
done

VALID_TYPES="eval-doc code-diff test-plan test-diff e2e-report issue coverage-matrix"
if ! echo "$VALID_TYPES" | grep -qw "$TYPE"; then
    echo "Error: invalid type '$TYPE'. Valid types: $VALID_TYPES" >&2
    exit 1
fi

VALID_STATUSES="draft confirmed executed archived"
if ! echo "$VALID_STATUSES" | grep -qw "$STATUS"; then
    echo "Error: invalid status '$STATUS'. Valid statuses: $VALID_STATUSES" >&2
    exit 1
fi

REGISTRY="$PROJECT_ROOT/.artifacts/registry.json"
if [[ ! -f "$REGISTRY" ]]; then
    echo "Error: registry not found at $REGISTRY. Run init-artifact-space.sh first." >&2
    exit 1
fi

# 生成唯一 ID：找当前类型的最大序号 +1
MAX_SEQ=$(python3 -c "
import json, sys
with open('$REGISTRY') as f:
    data = json.load(f)
max_seq = 0
for a in data['artifacts']:
    if a['type'] == '$TYPE':
        seq = int(a['id'].split('-')[-1])
        if seq > max_seq:
            max_seq = seq
print(max_seq)
")
NEXT_SEQ=$(printf "%03d" $((MAX_SEQ + 1)))
ARTIFACT_ID="${TYPE}-${NEXT_SEQ}"

# 构建 related_ids JSON 数组
if [[ -n "$RELATED" ]]; then
    RELATED_JSON=$(echo "$RELATED" | tr ',' '\n' | sed 's/^/"/;s/$/"/' | paste -sd ',' | sed 's/^/[/;s/$/]/')
else
    RELATED_JSON="[]"
fi

NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if $DRY_RUN; then
    echo "[dry-run] Would register artifact:"
    echo "  ID: $ARTIFACT_ID"
    echo "  Type: $TYPE"
    echo "  Name: $NAME"
    echo "  Producer: $PRODUCER"
    echo "  Path: $ARTIFACT_PATH"
    echo "  Status: $STATUS"
    echo "  Related: $RELATED_JSON"
    echo "[dry-run] Would update $REGISTRY"
    echo "[dry-run] Would run: git add .artifacts/ && git commit"
    exit 0
fi

# 写入 registry.json
python3 -c "
import json
with open('$REGISTRY') as f:
    data = json.load(f)
data['artifacts'].append({
    'id': '$ARTIFACT_ID',
    'name': '''$NAME''',
    'type': '$TYPE',
    'status': '$STATUS',
    'producer': '$PRODUCER',
    'consumers': [],
    'path': '$ARTIFACT_PATH',
    'created_at': '$NOW',
    'updated_at': '$NOW',
    'related_ids': $RELATED_JSON
})
with open('$REGISTRY', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
"

# 如果有 related，双向更新
if [[ -n "$RELATED" ]]; then
    IFS=',' read -ra REL_IDS <<< "$RELATED"
    for rel_id in "${REL_IDS[@]}"; do
        python3 -c "
import json
with open('$REGISTRY') as f:
    data = json.load(f)
for a in data['artifacts']:
    if a['id'] == '$rel_id' and '$ARTIFACT_ID' not in a.get('related_ids', []):
        a.setdefault('related_ids', []).append('$ARTIFACT_ID')
with open('$REGISTRY', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
"
    done
fi

# Git commit
cd "$PROJECT_ROOT"
git add .artifacts/ >&2
git commit -m "artifact: register $ARTIFACT_ID ($TYPE)" >&2

echo "$ARTIFACT_ID"
