#!/usr/bin/env bash
# Mode-aware setup — T7S.4 (spec §3.5).
#
# Reads deployment_mode from .autoservice/config.local.yaml:
#   master (default for fresh installs) — M1 behavior:
#     • .claude/{skills,commands,agents,hooks} -> top-level dirs
#     • scan plugins/*/skills/*/ and link into skills/<name>
#       (skip _example, _local_admin)
#     • init .autoservice/{logs,data,cache,sandbox,run,database}
#   tenant — fork runtime:
#     • requires tenant_id (else exit 1 with pointer to runbook)
#     • .claude/skills -> plugins/<tid>/skills (if the dir exists)
#     • .claude/{commands,agents,hooks} still link to top-level dirs
#     • plugin discovery limited to plugins/<tid>/
#     • init .autoservice/{logs,data,cache,sandbox,run,database}
#
# Idempotent: re-runs are safe and do not delete user data.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG_FILE=".autoservice/config.local.yaml"

# ── 1. Load deployment mode + tenant id ─────────────────────────────────────
MODE="master"   # fresh-install default
TENANT_ID=""

if [ -f "$CONFIG_FILE" ]; then
  # Prefer python+yaml; fall back to pure-bash grep if python is unavailable.
  if command -v python3 >/dev/null 2>&1; then
    PY=python3
  elif command -v python >/dev/null 2>&1; then
    PY=python
  else
    PY=""
  fi

  if [ -n "$PY" ]; then
    PARSED="$("$PY" - "$CONFIG_FILE" <<'PYEOF' 2>/dev/null || true
import sys
try:
    import yaml
except Exception:
    sys.exit(0)
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        cfg = yaml.safe_load(fh) or {}
except Exception:
    sys.exit(0)
mode = str(cfg.get('deployment_mode') or 'master').strip() or 'master'
tid = cfg.get('tenant_id')
tid = '' if tid is None else str(tid).strip()
print(f"{mode}\t{tid}")
PYEOF
)"
    if [ -n "$PARSED" ]; then
      MODE="$(printf '%s' "$PARSED" | cut -f1)"
      TENANT_ID="$(printf '%s' "$PARSED" | cut -f2)"
    fi
  fi

  # Pure-bash fallback (covers environments without pyyaml) — only reads
  # the two fields we care about and ignores the rest of the document.
  if [ -z "${MODE:-}" ] || [ "$MODE" = "master" ] && [ -z "${TENANT_ID:-}" ]; then
    if grep -Eq '^deployment_mode:' "$CONFIG_FILE" 2>/dev/null; then
      fallback_mode="$(grep -E '^deployment_mode:' "$CONFIG_FILE" | head -1 \
        | sed -E 's/^deployment_mode:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]+$//; s/^"//; s/"$//')"
      if [ -n "$fallback_mode" ]; then
        MODE="$fallback_mode"
      fi
    fi
    if grep -Eq '^tenant_id:' "$CONFIG_FILE" 2>/dev/null; then
      fallback_tid="$(grep -E '^tenant_id:' "$CONFIG_FILE" | head -1 \
        | sed -E 's/^tenant_id:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]+$//; s/^"//; s/"$//')"
      if [ "$fallback_tid" != "null" ] && [ "$fallback_tid" != "~" ]; then
        TENANT_ID="$fallback_tid"
      fi
    fi
  fi
fi

# Normalize: empty/missing → master
if [ -z "${MODE:-}" ]; then
  MODE="master"
fi

echo "[setup] deployment_mode=$MODE tenant_id=${TENANT_ID:-<none>}"

# ── 2. Runtime directories (shared) ─────────────────────────────────────────
mkdir -p \
  .autoservice/logs \
  .autoservice/data \
  .autoservice/cache \
  .autoservice/sandbox \
  .autoservice/run \
  .autoservice/database
echo "[setup] runtime dirs ready under .autoservice/"

# ── 3. helpers ──────────────────────────────────────────────────────────────
# safe_link <target> <link> — idempotently create/refresh a symlink so that
# <link> points at <target>. If <link> is already a symlink pointing at the
# same target, we're done. Otherwise remove whatever is there (symlink,
# broken link, or directory created by an earlier Windows-style ln that
# copied instead of linking) and recreate. Callers pass paths that are safe
# to clobber (they live inside .claude/ or skills/, never .autoservice/).
safe_link() {
  local target="$1"
  local link="$2"
  if [ -L "$link" ]; then
    if [ "$(readlink "$link" 2>/dev/null || true)" = "$target" ]; then
      return 0
    fi
    rm -f "$link" 2>/dev/null || true
  elif [ -e "$link" ]; then
    # Existing file or directory (including Git-Bash's directory-copy
    # fallback for `ln -s DIR`). Remove so we can relink cleanly.
    rm -rf "$link" 2>/dev/null || true
  fi
  ln -sfn "$target" "$link"
}

# ── 4. .claude/ base dirs (commands / agents / hooks) ───────────────────────
mkdir -p .claude
for dir in commands agents hooks; do
  if [ -d "$dir" ]; then
    safe_link "../$dir" ".claude/$dir"
    echo "[setup]   .claude/$dir -> ../$dir"
  fi
done

# ── 5. Mode-specific: .claude/skills + plugin discovery ─────────────────────
link_skills_dir() {
  # $1 = target relative path (e.g. ../skills or ../plugins/foo/skills)
  local target="$1"
  safe_link "$target" ".claude/skills"
  echo "[setup]   .claude/skills -> $target"
}

case "$MODE" in
  tenant)
    if [ -z "${TENANT_ID:-}" ] || [ "$TENANT_ID" = "null" ]; then
      echo "[setup] ERROR: deployment_mode=tenant requires tenant_id in $CONFIG_FILE" >&2
      echo "[setup]        see spec §3.4 LocalTarballForkCreator runbook step 4" >&2
      exit 1
    fi

    mkdir -p "plugins/$TENANT_ID"
    if [ ! -e "plugins/$TENANT_ID/skills" ]; then
      # Fork plugin tarballs may ship without per-tenant skills — link the
      # shared skills/ tree as a sensible default so tenant admin can still
      # use dev tools. If the tarball includes its own skills/ dir, honour it.
      if [ -d skills ]; then
        safe_link "../../skills" "plugins/$TENANT_ID/skills"
        echo "[setup]   plugins/$TENANT_ID/skills -> ../../skills"
      fi
    fi

    if [ -d "plugins/$TENANT_ID/skills" ]; then
      link_skills_dir "../plugins/$TENANT_ID/skills"
    elif [ -d skills ]; then
      # No per-tenant skills dir — fall back to shared.
      link_skills_dir "../skills"
    fi

    # Plugin discovery: only scan plugins/<tid>/ (skip _local_admin).
    if [ -d skills ]; then
      found=0
      for skill_dir in "plugins/$TENANT_ID"/skills/*/; do
        [ -d "$skill_dir" ] || continue
        name="$(basename "$skill_dir")"
        case "$name" in
          _local_admin) continue ;;
        esac
        # If skills/<name> is already a real directory (e.g. shipped with
        # the shared skills tree), leave it alone — tenant plugin skills
        # should not overwrite first-party skills of the same name.
        if [ -e "skills/$name" ] && [ ! -L "skills/$name" ]; then
          continue
        fi
        rel_target="../$skill_dir"
        safe_link "$rel_target" "skills/$name"
        echo "[setup]   skills/$name -> $rel_target"
        found=$((found+1))
      done
      echo "[setup] tenant plugin skills linked: $found"
    fi
    ;;
  master|"")
    MODE="master"
    if [ -d skills ]; then
      link_skills_dir "../skills"
    fi

    # M1 behavior: scan plugins/*/skills/*/, skip _example and _local_admin.
    if [ -d skills ]; then
      found=0
      for skill_dir in plugins/*/skills/*/; do
        [ -d "$skill_dir" ] || continue
        plugin_name="$(basename "$(dirname "$(dirname "$skill_dir")")")"
        name="$(basename "$skill_dir")"
        case "$plugin_name" in
          _example|_local_admin) continue ;;
        esac
        case "$name" in
          _local_admin) continue ;;
        esac
        # Don't clobber real skill dirs of the same name.
        if [ -e "skills/$name" ] && [ ! -L "skills/$name" ]; then
          continue
        fi
        rel_target="../$skill_dir"
        safe_link "$rel_target" "skills/$name"
        echo "[setup]   skills/$name -> $rel_target"
        found=$((found+1))
      done
      echo "[setup] master plugin skills linked: $found"
    fi
    ;;
  *)
    echo "[setup] ERROR: unknown deployment_mode '$MODE' (expected master|tenant)" >&2
    exit 1
    ;;
esac

echo "[setup] done (mode=$MODE)"
