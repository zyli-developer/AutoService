#!/usr/bin/env bash
# scripts/refine-pull.sh — Pull refinable commits from L3 forks into L2
#
# Scans registered L3 forks (or a specific repo) for commits that modify
# L1/L2 files but aren't yet in the upstream. Lists candidates, optionally
# cherry-picks them automatically.
#
# Usage:
#   ./scripts/refine-pull.sh                           # Scan all registered forks
#   ./scripts/refine-pull.sh --repo <path-or-remote>   # Scan a specific fork
#   ./scripts/refine-pull.sh --repo ../AutoService-Cinnox --auto
#
# Options:
#   --repo <path>   Local path or git remote name of an L3 fork
#   --auto          Auto cherry-pick all candidates + create branch (no prompt)
#   --dry-run       List candidates only, don't cherry-pick
#   --pr            After cherry-pick, push and create PR (requires gh CLI)
#   -h, --help      Show help

set -euo pipefail

REGISTRY="docs/fork-registry.yaml"

# L2 file patterns — commits touching these are refine candidates
L2_PATHS="channels/ autoservice/ socialware/ tests/ scripts/ Makefile"

# Defaults
REPO=""
AUTO=false
DRY_RUN=false
CREATE_PR=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --repo)    REPO="$2"; shift 2 ;;
    --auto)    AUTO=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --pr)      CREATE_PR=true; shift ;;
    -h|--help)
      sed -n '2,/^$/{ s/^# //; s/^#//; p }' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "=== Refine Pull: L3 → L2 ==="
echo ""

# ---------------------------------------------------------------------------
# Collect fork sources
# ---------------------------------------------------------------------------

FORK_REFS=()   # Array of "name:ref" pairs (ref = remote name or local path)

if [ -n "$REPO" ]; then
  # Single repo mode
  FORK_NAME=$(basename "$REPO" | sed 's/[^a-zA-Z0-9_-]/-/g')
  # Add as git remote if it's a local path
  if [ -d "$REPO/.git" ]; then
    REMOTE_NAME="refine-$FORK_NAME"
    if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
      git remote add "$REMOTE_NAME" "$REPO"
      echo "Added remote: $REMOTE_NAME -> $REPO"
    fi
    git fetch "$REMOTE_NAME" main --quiet 2>/dev/null
    FORK_REFS+=("$FORK_NAME:$REMOTE_NAME/main")
  elif git remote get-url "$REPO" &>/dev/null; then
    git fetch "$REPO" main --quiet 2>/dev/null
    FORK_REFS+=("$FORK_NAME:$REPO/main")
  else
    echo "Error: '$REPO' is not a local repo or known remote."
    exit 1
  fi
elif [ -f "$REGISTRY" ]; then
  # Registry mode — scan all active forks
  if ! command -v yq &>/dev/null; then
    # Fallback: grep-based extraction
    while IFS= read -r line; do
      name=$(echo "$line" | awk '{print $2}')
      # Try to find matching repo line
      repo_line=$(grep -A5 "name: $name" "$REGISTRY" | grep "repo:" | head -1 | awk '{print $2}')
      status_line=$(grep -A5 "name: $name" "$REGISTRY" | grep "status:" | head -1 | awk '{print $2}')
      [ "$status_line" != "active" ] && continue
      if [ -n "$repo_line" ]; then
        REMOTE_NAME="refine-$name"
        if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
          # Try GitHub first
          git remote add "$REMOTE_NAME" "https://github.com/$repo_line.git" 2>/dev/null || true
        fi
        if git fetch "$REMOTE_NAME" main --quiet 2>/dev/null; then
          FORK_REFS+=("$name:$REMOTE_NAME/main")
        else
          echo "  WARNING: Cannot fetch from $repo_line, skipping"
        fi
      fi
    done < <(grep "  - name:" "$REGISTRY" 2>/dev/null)
  else
    FORK_COUNT=$(yq '.forks | length' "$REGISTRY")
    for i in $(seq 0 $((FORK_COUNT - 1))); do
      name=$(yq ".forks[$i].name" "$REGISTRY")
      repo=$(yq ".forks[$i].repo" "$REGISTRY")
      status=$(yq ".forks[$i].status" "$REGISTRY")
      [ "$status" != "active" ] && continue
      REMOTE_NAME="refine-$name"
      if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
        git remote add "$REMOTE_NAME" "https://github.com/$repo.git" 2>/dev/null || true
      fi
      if git fetch "$REMOTE_NAME" main --quiet 2>/dev/null; then
        FORK_REFS+=("$name:$REMOTE_NAME/main")
      else
        echo "  WARNING: Cannot fetch from $repo, skipping"
      fi
    done
  fi
fi

if [ ${#FORK_REFS[@]} -eq 0 ]; then
  echo "No forks to scan."
  echo "Use --repo <path> or register forks in $REGISTRY"
  exit 0
fi

# ---------------------------------------------------------------------------
# Scan each fork for refinable commits
# ---------------------------------------------------------------------------

CANDIDATES=()    # "hash:fork_name:subject" entries
TOTAL_SCANNED=0

for fork_entry in "${FORK_REFS[@]}"; do
  fork_name="${fork_entry%%:*}"
  fork_ref="${fork_entry#*:}"

  echo "Scanning: $fork_name ($fork_ref)"

  # Find commits in fork but not in HEAD, excluding merges.
  #
  # Strategy: only consider commits AFTER the last sync merge in the fork.
  # This filters out historical commits that were already incorporated
  # via architecture migrations (not cherry-pick).
  LAST_SYNC_IN_FORK=$(git log --oneline --grep="^sync:" "$fork_ref" -1 --format="%H" 2>/dev/null || true)
  if [ -n "$LAST_SYNC_IN_FORK" ]; then
    SCAN_RANGE="$LAST_SYNC_IN_FORK..$fork_ref"
    echo "  (scanning after last sync: $(git log -1 --oneline "$LAST_SYNC_IN_FORK"))"
  else
    SCAN_RANGE="HEAD..$fork_ref"
    echo "  (no sync commit found, scanning all)"
  fi

  while IFS= read -r line; do
    hash=$(echo "$line" | awk '{print $1}')
    subject=$(echo "$line" | cut -d' ' -f2-)

    # Check if this commit touches L2 paths
    files_changed=$(git diff-tree --no-commit-id --name-only -r "$hash" -- $L2_PATHS 2>/dev/null)
    if [ -n "$files_changed" ]; then
      # Check it's not already in HEAD (by patch-id match)
      fork_patch_id=$(git patch-id --stable < <(git diff-tree -p "$hash") 2>/dev/null | awk '{print $1}')
      already_applied=false
      if [ -n "$fork_patch_id" ]; then
        for head_hash in $(git log --oneline -50 --format="%H" HEAD); do
          head_patch_id=$(git patch-id --stable < <(git diff-tree -p "$head_hash") 2>/dev/null | awk '{print $1}')
          if [ "$fork_patch_id" = "$head_patch_id" ] && [ -n "$head_patch_id" ]; then
            already_applied=true
            break
          fi
        done
      fi

      if [ "$already_applied" = false ]; then
        CANDIDATES+=("$hash:$fork_name:$subject")
        file_count=$(echo "$files_changed" | wc -l | tr -d ' ')
        echo "  [CANDIDATE] $hash $subject ($file_count L2 files)"
      else
        echo "  [SKIP] $hash $subject (already applied)"
      fi
    fi

    TOTAL_SCANNED=$((TOTAL_SCANNED + 1))
  done < <(git log --oneline --no-merges "$SCAN_RANGE" 2>/dev/null)

  echo ""
done

echo "Scanned $TOTAL_SCANNED commits, found ${#CANDIDATES[@]} candidate(s)."
echo ""

if [ ${#CANDIDATES[@]} -eq 0 ]; then
  echo "Nothing to refine."
  exit 0
fi

# ---------------------------------------------------------------------------
# Display candidates
# ---------------------------------------------------------------------------

echo "=== Refine Candidates ==="
echo ""
printf "  %-3s %-10s %-12s %s\n" "#" "HASH" "FORK" "SUBJECT"
printf "  %-3s %-10s %-12s %s\n" "---" "----------" "------------" "-------"

i=1
for entry in "${CANDIDATES[@]}"; do
  hash="${entry%%:*}"
  rest="${entry#*:}"
  fork="${rest%%:*}"
  subject="${rest#*:}"
  printf "  %-3d %-10s %-12s %s\n" "$i" "${hash:0:10}" "$fork" "$subject"
  i=$((i + 1))
done
echo ""

# ---------------------------------------------------------------------------
# Dry-run stops here
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" = true ]; then
  echo "[dry-run] Would cherry-pick ${#CANDIDATES[@]} commit(s)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Confirm and cherry-pick
# ---------------------------------------------------------------------------

if [ "$AUTO" = false ]; then
  read -rp "Cherry-pick all ${#CANDIDATES[@]} candidate(s)? [y/N]: " CONFIRM
  [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ] && { echo "Aborted."; exit 0; }
fi

# Create refine branch
BRANCH_NAME="upstream/refine-pull-$(date +%Y%m%d)"
echo ""
echo "==> Creating branch: $BRANCH_NAME"
git checkout -b "$BRANCH_NAME"

PICKED=0
FAILED=0

for entry in "${CANDIDATES[@]}"; do
  hash="${entry%%:*}"
  rest="${entry#*:}"
  subject="${rest#*:}"

  echo -n "  Cherry-picking $hash... "
  if git cherry-pick "$hash" --allow-empty 2>/dev/null; then
    echo "OK"
    PICKED=$((PICKED + 1))
  else
    echo "CONFLICT"
    git cherry-pick --abort 2>/dev/null || true
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "==> Results: $PICKED picked, $FAILED failed"

if [ "$PICKED" -eq 0 ]; then
  echo "No commits picked. Returning to previous branch."
  git checkout - 2>/dev/null
  git branch -D "$BRANCH_NAME" 2>/dev/null || true
  exit 0
fi

# ---------------------------------------------------------------------------
# Push + PR (if requested)
# ---------------------------------------------------------------------------

if [ "$CREATE_PR" = true ] || [ "$AUTO" = true ]; then
  echo ""
  echo "==> Pushing branch..."
  git push -u origin "$BRANCH_NAME" 2>/dev/null

  if command -v gh &>/dev/null; then
    echo "==> Creating PR..."
    BODY="## Refined from L3 forks

Cherry-picked $PICKED commit(s) that modify L2 files:

$(for entry in "${CANDIDATES[@]}"; do
  hash="${entry%%:*}"
  rest="${entry#*:}"
  fork="${rest%%:*}"
  subject="${rest#*:}"
  echo "- \`${hash:0:10}\` ($fork) $subject"
done)

### Sync safety
All commits are identical to L3 originals — next \`make sync\` will auto-merge with zero conflicts.

Generated by \`scripts/refine-pull.sh\`"

    gh pr create \
      --title "refine(L3→L2): $([ $PICKED -eq 1 ] && echo "$subject" || echo "$PICKED fixes from L3 forks")" \
      --body "$BODY" \
      --base dev 2>/dev/null && echo "PR created." || echo "PR creation failed."
  fi
fi

echo ""
echo "Done. Branch: $BRANCH_NAME"
