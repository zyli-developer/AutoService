"""Publish pipeline — sandbox → tarball + runbook + archive (T1B.7).

Implements the publish-gate + tarball build + freeze/archive + ForkCreator
abstraction described in
docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §6 and §7.

High-level flow (driven by ``publish()``):

    1. ``check_publish_gate()``  — 4 conditions:
         a. compliance.risk_level != "critical"    (override possible with signer)
         b. rehearsal.json: all 12 dialogs reviewed (no pending)
         c. 4 souls (customer/translate/lead/triage) exist on disk
         d. kb.db ≥ 50 chunks                       (warning-only)

    2. ``build_publish_archive()`` — produce
         ``.autoservice/published/tenant_<tid>_publish_<ts>.tar.gz``
       whose contents unpack into fork-shape:
         ``plugins/<tid>/{plugin.yaml, config.json, souls/*.md,
                          kb/kb.db, rehearsal_baseline.json, README.md}``

    3. ``write_publish_record()`` — ``.autoservice/published/<tid>.json``
       with artifact path, sha256, gate results, archive target.

    4. ``write_runbook()`` — ``.autoservice/published/<tid>_PUBLISH_RUNBOOK.md``
       auto-generated manual steps (gh repo fork / tar -xzf / make check / ...).

    5. ``freeze_sandbox()`` — flip config.json.status to
       ``published_pending_fork`` (sandbox write paths must reject non-"sandbox").

    6. ``archive_sandbox()`` — physically move
         ``.autoservice/sandbox/<tid>/`` → ``.autoservice/archived/<tid>_<ts>/``

``unfreeze()`` reverses 5+6 for debug/misfire recovery.

The ``ForkCreator`` ``Protocol`` is a seam for M2 when the publish step will
actually call ``gh repo fork`` / GitHub API.  M1 ships ``LocalTarballForkCreator``
which produces tarball + runbook and leaves the git work as a manual runbook
step.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger("autoservice.publish")

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = PROJECT_ROOT / ".autoservice" / "sandbox"
ARCHIVED_ROOT = PROJECT_ROOT / ".autoservice" / "archived"
PUBLISHED_ROOT = PROJECT_ROOT / ".autoservice" / "published"

#: Soul roles that MUST exist at publish-time (gate check).  ``dream`` is a
#: placeholder in M1 and ships from a static template — the gate doesn't
#: require it, but the tarball includes it when present (§6.3).
REQUIRED_SOUL_ROLES: tuple[str, ...] = ("customer", "translate", "lead", "triage")

#: Minimum KB chunks recommended — below this the gate warns but does not
#: block (§6.2 "warning but pass").
KB_CHUNK_WARNING_THRESHOLD: int = 50


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Outcome of ``check_publish_gate()``.

    ``passed`` — ``True`` iff the publish can proceed (after applying
    override when supplied).  ``blocking_reasons`` is empty on success.

    ``warnings`` — non-fatal notes (currently: low KB chunk count).
    """

    passed: bool
    compliance_risk: str
    rehearsal_reviewed: int
    rehearsal_total: int
    souls_saved: int
    kb_chunks: int
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    override: bool = False
    signer: str | None = None

    def to_record(self) -> dict:
        """Shape used in ``.autoservice/published/<tid>.json``."""
        return {
            "compliance_risk": self.compliance_risk,
            "compliance_override": self.override,
            "compliance_signer": self.signer,
            "rehearsal_reviewed": self.rehearsal_reviewed,
            "rehearsal_total": self.rehearsal_total,
            "souls_saved": self.souls_saved,
            "kb_chunks": self.kb_chunks,
            "warnings": list(self.warnings),
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass
class ForkResult:
    """Return value of ``ForkCreator.create()``.

    M1 shape only includes the artifacts we really produced — ``repo_url``
    is reserved for M2 (``GitHubApiForkCreator``).
    """

    tenant_id: str
    artifact_path: Path
    runbook_path: Path
    repo_url: str | None = None


# ---------------------------------------------------------------------------
# ForkCreator Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ForkCreator(Protocol):
    """Strategy interface for turning a sandbox into a tenant fork.

    M1 default: ``LocalTarballForkCreator`` (produces tarball + runbook,
    no git automation).  M2 will add ``GitHubApiForkCreator`` which calls
    ``gh`` CLI / GitHub API to auto-fork + push + trigger CI.
    """

    def create(self, tenant_id: str, artifact_path: Path) -> ForkResult: ...


class LocalTarballForkCreator:
    """M1 default — produces tarball + runbook, no actual git work.

    The heavy lifting (tarball build) is done by ``build_publish_archive()``
    before ``ForkCreator.create()`` is invoked; this class is essentially
    a placeholder that records the artifact path and writes the runbook,
    matching the shape M2 will fill in with real automation.
    """

    def create(self, tenant_id: str, artifact_path: Path) -> ForkResult:
        runbook_path = write_runbook(tenant_id, artifact_path)
        return ForkResult(
            tenant_id=tenant_id,
            artifact_path=artifact_path,
            runbook_path=runbook_path,
            repo_url=None,
        )


# ---------------------------------------------------------------------------
# GitHubApiForkCreator (T8B.1, spec §3.4)
# ---------------------------------------------------------------------------


class ForkCreationError(Exception):
    """Raised when :class:`GitHubApiForkCreator` fails.

    Carries enough context (``phase`` + ``fork_name`` + underlying error)
    for a human to decide whether manual cleanup is needed.

    Per spec §9 red line, the creator NEVER runs a destructive cleanup
    command on failure — removal of a fork requires human confirmation.
    When ``fork_name`` is populated, the admin is expected to either
    verify the fork never came into existence, or remove it manually via
    their own tooling.

    Attributes:
        phase: Which step failed — ``"gh-check"`` (subprocess launch /
            FileNotFoundError), ``"gh-repo-fork"`` (gh returned non-zero
            or timed out).
        fork_name: Best-effort name of the fork GitHub MAY have created.
            ``None`` iff we failed before invoking ``gh repo fork`` at
            all (e.g. gh binary not found).  Otherwise a string like
            ``"AutoService-<tenant_id>"`` that the admin can pass to
            ``gh repo view`` / ``gh repo <manual-remove>``.
        original_error: The underlying ``subprocess`` / ``OSError`` —
            preserved so callers can rebuild the traceback if needed.
        stderr: Captured ``stderr`` from the gh invocation when applicable
            (CalledProcessError).  Always also logged at WARNING level.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        fork_name: Optional[str] = None,
        original_error: Optional[BaseException] = None,
        stderr: Optional[str] = None,
    ) -> None:
        self.phase = phase
        self.fork_name = fork_name
        self.original_error = original_error
        self.stderr = stderr
        # Single-line diagnostic — grep-friendly in logs
        parts = [f"phase={phase!r}"]
        if fork_name is not None:
            parts.append(f"fork_name={fork_name!r}")
        if stderr:
            # Truncate stderr to keep the message bounded
            snippet = stderr.strip()
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            parts.append(f"stderr={snippet!r}")
        if original_error is not None:
            parts.append(f"original_error={type(original_error).__name__}")
        super().__init__(f"{message} ({', '.join(parts)})")


# Module-level regex (pre-compiled) — validates tenant_id as a safe
# filesystem + yaml + git repo identifier (letters, digits, _ and -).
_VALID_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


class GitHubApiForkCreator:
    """gh CLI wrapper that creates a GitHub fork of the platform repo.

    Two entry points:

    - :meth:`create_fork` — only runs ``gh repo fork`` and returns the
      fork URL.  Useful when the caller wants to orchestrate the rest
      manually.
    - :meth:`create` — full ``ForkCreator`` Protocol: fork → clone →
      tarball extract → write ``.autoservice/config.local.yaml`` →
      ``git add/commit/push`` → return :class:`ForkResult`.  This is
      what :func:`publish` invokes when the admin selects
      ``fork_creator: github_api`` in ``.autoservice/config.local.yaml``.

    **Failure handling (spec §9)** — every failure phase raises
    :class:`ForkCreationError` with ``phase`` tagged so the admin knows
    where in the pipeline it broke:

    - ``"gh-check"`` — ``gh`` CLI missing (pre-invoke, no fork created,
      ``fork_name=None``).
    - ``"gh-repo-fork"`` — ``gh repo fork`` failed; fork MAY exist,
      ``fork_name`` populated.
    - ``"gh-repo-clone"`` — fork succeeded but clone failed.
    - ``"tar-extract"`` — tarball corrupt / IO failure after clone.
    - ``"git-add"`` / ``"git-commit"`` / ``"git-push"`` — git step failed
      after tarball extract; local clone still has the pending commit
      on disk under the temp dir.

    **NEVER** issues a destructive cleanup command automatically — spec §9
    mandates human confirmation.  When a post-fork phase fails, the
    exception carries ``fork_name`` so the admin can decide whether to
    retry or remove the fork manually via their own tooling.

    Every subprocess invocation uses an explicit ``timeout`` + captures
    ``stderr``; stderr is WARNING-logged on failure so it is never silently
    swallowed.
    """

    _AUTH_CHECK_TIMEOUT_SEC = 30
    _FORK_CREATE_TIMEOUT_SEC = 60
    _CLONE_TIMEOUT_SEC = 120
    _GIT_TIMEOUT_SEC = 120

    def __init__(
        self,
        *,
        gh_bin: str = "gh",
        source_repo: str = "ezagent42/AutoService",
        org: Optional[str] = None,
    ) -> None:
        self.gh_bin = gh_bin
        self.source_repo = source_repo
        self.org = org

    # -- probes --------------------------------------------------------

    def available(self) -> bool:
        """Return True iff ``gh`` is installed AND authenticated.

        Safe to call defensively — never raises.  Callers typically use
        this to decide between :class:`GitHubApiForkCreator` and
        :class:`LocalTarballForkCreator` (spec §3.4 selector).
        """
        try:
            subprocess.run(
                [self.gh_bin, "auth", "status"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._AUTH_CHECK_TIMEOUT_SEC,
            )
            return True
        except FileNotFoundError:
            return False
        except subprocess.CalledProcessError:
            return False
        except subprocess.TimeoutExpired:
            return False

    # -- actions -------------------------------------------------------

    def create_fork(self, tenant_id: str) -> str:
        """Create a GitHub fork named after ``tenant_id``.

        Returns:
            The fork URL as reported by ``gh`` on stdout.

        Raises:
            ValueError: tenant_id empty / whitespace / fails the
                identifier regex (rejected before any subprocess runs).
            ForkCreationError: on any subprocess failure.  Inspect
                ``.phase`` and ``.fork_name`` to decide on cleanup.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        tenant_id = tenant_id.strip()
        # Defense-in-depth: even though the HTTP route validates tenant_id,
        # this method is a public API surface that CLI / test callers may
        # reach directly.  An unvalidated tenant_id lands in argv, the fork
        # name, and (via `create()`) a git commit message.
        if not _VALID_TENANT_ID_RE.match(tenant_id):
            raise ValueError(
                f"tenant_id {tenant_id!r} is not a valid identifier — "
                f"must match {_VALID_TENANT_ID_RE.pattern}"
            )

        fork_name = f"AutoService-{tenant_id}"
        # Target: org-qualified when org set; else bare fork name (user
        # namespace).  gh's --fork-name flag accepts either form.
        target = f"{self.org}/{fork_name}" if self.org else fork_name

        argv = [
            self.gh_bin,
            "repo",
            "fork",
            self.source_repo,
            f"--fork-name={target}",
            "--clone=false",
        ]

        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=True,
                timeout=self._FORK_CREATE_TIMEOUT_SEC,
            )
        except FileNotFoundError as exc:
            # gh binary itself is missing — no fork was created.
            raise ForkCreationError(
                "gh CLI not found — install from https://cli.github.com "
                "or use LocalTarballForkCreator",
                phase="gh-check",
                fork_name=None,
                original_error=exc,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            # Subprocess may have started the fork before timing out —
            # admin must verify + clean up manually.
            log.warning(
                "gh repo fork timed out after %ss for tenant %s (fork %s)",
                self._FORK_CREATE_TIMEOUT_SEC,
                tenant_id,
                fork_name,
            )
            raise ForkCreationError(
                f"gh repo fork timed out after "
                f"{self._FORK_CREATE_TIMEOUT_SEC}s — fork MAY exist, check "
                f"manually",
                phase="gh-repo-fork",
                fork_name=fork_name,
                original_error=exc,
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr or ""
            # WARNING — never silently swallow stderr (spec §9 Yellow note).
            log.warning(
                "gh repo fork failed for tenant %s (fork %s): exit=%s stderr=%s",
                tenant_id,
                fork_name,
                exc.returncode,
                stderr_text.strip() or "<empty>",
            )
            raise ForkCreationError(
                f"gh repo fork failed with exit={exc.returncode}",
                phase="gh-repo-fork",
                fork_name=fork_name,
                original_error=exc,
                stderr=stderr_text,
            ) from exc

        stdout = (completed.stdout or "").strip()
        # `gh repo fork` typically prints a single URL on success; if the
        # user already has the fork, gh may print nothing / a notice.
        # Extract the first https URL we find; fall back to the computed
        # URL when gh was quiet.
        url = _extract_first_url(stdout)
        if url:
            return url
        # Fallback — synthesize the most likely URL so callers always
        # have a usable return value.
        owner = self.org or "<user>"
        return f"https://github.com/{owner}/{fork_name}"

    # -- full pipeline (ForkCreator Protocol) --------------------------

    def create(self, tenant_id: str, artifact_path: Path) -> "ForkResult":
        """Full ``ForkCreator.create()`` — fork + clone + extract + push.

        Pipeline:
          1. :meth:`create_fork` — ``gh repo fork`` (phase ``gh-repo-fork``)
          2. ``gh repo clone`` into a fresh temp dir (phase ``gh-repo-clone``)
          3. Extract ``artifact_path`` under the clone via :mod:`tarfile`
             (phase ``tar-extract``)
          4. Write ``.autoservice/config.local.yaml`` via
             :func:`_fork_local_config_yaml_text`
          5. ``git add plugins/ .autoservice/config.local.yaml`` (phase
             ``git-add``)
          6. ``git commit -m "Install tenant <tid>"`` (phase ``git-commit``)
          7. ``git push`` (phase ``git-push``)
          8. :func:`write_runbook` — informational record of what the
             automation did (parallel to the human-oriented M1 runbook)

        The clone dir is NOT removed on success or failure — admins often
        want to inspect it.  ``tempfile.mkdtemp`` gives it a unique name
        under the system temp dir.

        Any failure after step 1 raises :class:`ForkCreationError` with
        ``fork_name`` populated so the admin can decide cleanup / retry.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        tenant_id = tenant_id.strip()
        # Fail-fast on unsafe identifiers BEFORE fork / clone / git — see
        # create_fork() for rationale.
        if not _VALID_TENANT_ID_RE.match(tenant_id):
            raise ValueError(
                f"tenant_id {tenant_id!r} is not a valid identifier — "
                f"must match {_VALID_TENANT_ID_RE.pattern}"
            )

        fork_name = f"AutoService-{tenant_id}"
        full_fork_ref = f"{self.org}/{fork_name}" if self.org else fork_name

        # Step 1: fork — raises ForkCreationError on its own phases.
        repo_url = self.create_fork(tenant_id)

        # Step 2: clone into a fresh dir under the system temp root.
        # mkdtemp creates the parent with 0700 on POSIX (random name — not
        # predictable, not world-readable); gh repo clone creates the
        # child.  On Windows the TMP dir is already under the per-user
        # %LOCALAPPDATA%, so no cross-user risk either.
        clone_parent = Path(tempfile.mkdtemp(prefix="autoservice-fork-"))
        clone_dir = clone_parent / fork_name
        try:
            self._run_gh_clone(full_fork_ref, clone_dir, fork_name)
        except ForkCreationError:
            # Tidy up the empty parent so repeated publish failures don't
            # leak scaffold dirs.  NOT "auto-delete" in the spec §9 sense —
            # §9 is about remote GitHub forks, not local temp.
            shutil.rmtree(clone_parent, ignore_errors=True)
            raise

        # Step 3: extract tarball.
        self._extract_tarball(artifact_path, clone_dir, fork_name)

        # Step 4: write config.local.yaml.
        cfg_path = clone_dir / ".autoservice" / "config.local.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            _fork_local_config_yaml_text(tenant_id), encoding="utf-8"
        )

        # Steps 5-7: git add + commit + push.
        self._run_git(
            ["git", "add", "plugins/", ".autoservice/config.local.yaml"],
            cwd=clone_dir,
            phase="git-add",
            fork_name=fork_name,
        )
        self._run_git(
            ["git", "commit", "-m", f"Install tenant {tenant_id}"],
            cwd=clone_dir,
            phase="git-commit",
            fork_name=fork_name,
        )
        self._run_git(
            ["git", "push"],
            cwd=clone_dir,
            phase="git-push",
            fork_name=fork_name,
        )

        # Step 8: runbook (informational — records the automated pipeline).
        runbook_path = write_runbook(tenant_id, artifact_path)

        return ForkResult(
            tenant_id=tenant_id,
            artifact_path=artifact_path,
            runbook_path=runbook_path,
            repo_url=repo_url,
        )

    # -- internal subprocess helpers -----------------------------------

    def _run_gh_clone(
        self, full_fork_ref: str, clone_dir: Path, fork_name: str
    ) -> None:
        """``gh repo clone <ref> <dir>`` with unified error phasing."""
        argv = [
            self.gh_bin,
            "repo",
            "clone",
            full_fork_ref,
            str(clone_dir),
        ]
        try:
            subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=True,
                timeout=self._CLONE_TIMEOUT_SEC,
            )
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr or ""
            log.warning(
                "gh repo clone failed for fork %s: exit=%s stderr=%s",
                fork_name,
                exc.returncode,
                stderr_text.strip() or "<empty>",
            )
            raise ForkCreationError(
                f"gh repo clone failed with exit={exc.returncode}",
                phase="gh-repo-clone",
                fork_name=fork_name,
                original_error=exc,
                stderr=stderr_text,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            log.warning(
                "gh repo clone timed out after %ss for fork %s",
                self._CLONE_TIMEOUT_SEC,
                fork_name,
            )
            raise ForkCreationError(
                f"gh repo clone timed out after {self._CLONE_TIMEOUT_SEC}s",
                phase="gh-repo-clone",
                fork_name=fork_name,
                original_error=exc,
            ) from exc

    def _extract_tarball(
        self, artifact_path: Path, clone_dir: Path, fork_name: str
    ) -> None:
        """Extract ``artifact_path`` into ``clone_dir`` with phased errors.

        Uses ``filter="data"`` (PEP 706) — refuses absolute paths, ``..``
        traversal, symlinks pointing outside the dest, and unexpected
        owners/modes.  Python 3.14+ requires an explicit filter; earlier
        versions warn.  ``data`` is the tightest built-in filter and
        appropriate for trusted-but-verify tarballs like ours.
        """
        try:
            with tarfile.open(artifact_path, "r:gz") as tf:
                tf.extractall(clone_dir, filter="data")
        except (tarfile.TarError, OSError, ValueError) as exc:
            log.warning(
                "tarball extraction failed for fork %s (artifact=%s): %s",
                fork_name,
                artifact_path,
                exc,
            )
            raise ForkCreationError(
                f"tarball extraction failed: {exc}",
                phase="tar-extract",
                fork_name=fork_name,
                original_error=exc,
            ) from exc

    def _run_git(
        self,
        argv: list,
        *,
        cwd: Path,
        phase: str,
        fork_name: str,
    ) -> None:
        """Run a git subcommand under ``cwd`` with unified error phasing."""
        try:
            subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
                timeout=self._GIT_TIMEOUT_SEC,
            )
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr or ""
            log.warning(
                "git %s failed for fork %s: exit=%s stderr=%s",
                argv[1] if len(argv) > 1 else "?",
                fork_name,
                exc.returncode,
                stderr_text.strip() or "<empty>",
            )
            raise ForkCreationError(
                f"git {argv[1]} failed with exit={exc.returncode}",
                phase=phase,
                fork_name=fork_name,
                original_error=exc,
                stderr=stderr_text,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            log.warning(
                "git %s timed out after %ss for fork %s",
                argv[1] if len(argv) > 1 else "?",
                self._GIT_TIMEOUT_SEC,
                fork_name,
            )
            raise ForkCreationError(
                f"git {argv[1]} timed out after {self._GIT_TIMEOUT_SEC}s",
                phase=phase,
                fork_name=fork_name,
                original_error=exc,
            ) from exc


def _extract_first_url(text: str) -> Optional[str]:
    """Return the first http(s) URL substring in ``text``, else None."""
    if not text:
        return None
    m = re.search(r"https?://\S+", text)
    if not m:
        return None
    return m.group(0).rstrip(".,;)")


def select_fork_creator_from_config(config_path: Path) -> Optional["ForkCreator"]:
    """Resolve the admin's ``fork_creator`` choice from ``config.local.yaml``.

    Returns:
        * ``GitHubApiForkCreator()`` — when the config sets
          ``fork_creator: github_api`` AND ``gh`` CLI is authed.
        * ``None`` — in every other case (config missing, key unset,
          ``fork_creator: local``, yaml malformed, or ``github_api``
          requested but ``gh`` unavailable).  A ``None`` return tells
          :func:`publish` to fall back to its default
          :class:`LocalTarballForkCreator`, which always works.

    Never raises — config read failures are logged at WARNING so the admin
    can spot them, but never block the publish flow.  The worst-case
    behavior is "fallback to M1 manual runbook", which is also the
    starting state.
    """
    if not config_path.exists():
        return None
    try:
        from socialware.config import load_config

        cfg = load_config(config_path) or {}
    except Exception as exc:
        log.warning(
            "Failed to read %s for fork_creator selection: %s", config_path, exc
        )
        return None

    if not isinstance(cfg, dict):
        log.warning(
            "%s must be a mapping; got %s — ignoring fork_creator selection",
            config_path,
            type(cfg).__name__,
        )
        return None

    name = str(cfg.get("fork_creator") or "").strip().lower()
    if name == "github_api":
        creator = GitHubApiForkCreator()
        if creator.available():
            return creator
        log.warning(
            "fork_creator=github_api requested in %s but gh CLI is unavailable; "
            "falling back to LocalTarballForkCreator",
            config_path,
        )
        return None
    return None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _sandbox_dir(tenant_id: str) -> Path:
    return SANDBOX_ROOT / tenant_id


def _published_record_path(tenant_id: str) -> Path:
    return PUBLISHED_ROOT / f"{tenant_id}.json"


def _archived_root_for(tenant_id: str, ts: str) -> Path:
    return ARCHIVED_ROOT / f"{tenant_id}_{ts}"


def _timestamp() -> str:
    """YYYYMMDD-HHMMSS, UTC, for filename/dir segment."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------

def _load_sandbox_config(tenant_id: str) -> dict:
    cfg_path = _sandbox_dir(tenant_id) / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"sandbox config.json not found for tenant {tenant_id!r}: {cfg_path}"
        )
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _count_kb_chunks(tenant_id: str) -> int:
    """Return COUNT(*) from kb_chunks, or 0 if DB missing/corrupt."""
    kb_path = _sandbox_dir(tenant_id) / "kb" / "kb.db"
    if not kb_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(kb_path))
        try:
            (count,) = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
            return int(count)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        log.warning("kb.db unreadable for tenant %s at %s", tenant_id, kb_path)
        return 0


def _count_rehearsal_reviewed(tenant_id: str) -> tuple[int, int]:
    """Return (reviewed_count, total_count) from rehearsal.json.

    A dialog is "reviewed" iff ``review_status != "pending"`` (spec §6.2).
    Missing file → (0, 0).
    """
    path = _sandbox_dir(tenant_id) / "rehearsal.json"
    if not path.exists():
        return (0, 0)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("rehearsal.json corrupt for tenant %s", tenant_id)
        return (0, 0)
    dialogs = data.get("dialogs") or []
    total = len(dialogs)
    reviewed = sum(
        1 for d in dialogs if (d.get("review_status") or "pending") != "pending"
    )
    return (reviewed, total)


def _count_required_souls(tenant_id: str) -> int:
    """Number of required-role soul files present on disk."""
    souls_dir = _sandbox_dir(tenant_id) / "souls"
    if not souls_dir.exists():
        return 0
    return sum(
        1 for role in REQUIRED_SOUL_ROLES
        if (souls_dir / f"{role}_soul.md").exists()
    )


def _run_compliance_scan(tenant_id: str, config: dict) -> str:
    """Run ComplianceEngine on the sandbox config and return risk_level string.

    On error returns ``"unknown"`` — callers treat anything not in the
    known set as non-blocking, and the gate ONLY blocks on ``"critical"``.
    """
    try:
        from autoservice.compliance.compliance import ComplianceEngine

        nested: dict = {"tenant": {k: v for k, v in config.items() if k != "soul"}}
        if "soul" in config:
            nested["soul"] = config["soul"]
        engine = ComplianceEngine()
        report = engine.scan(tenant_id, nested)
        return report.risk_level.value
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("compliance scan failed for %s: %s", tenant_id, exc)
        return "unknown"


def check_publish_gate(
    tenant_id: str,
    *,
    override: bool = False,
    signer: str | None = None,
) -> GateResult:
    """Evaluate the 4 publish-gate conditions for ``tenant_id``.

    Raises ``FileNotFoundError`` if the sandbox config is missing — that
    is a caller-side precondition error, not a gate failure.

    The returned ``GateResult.passed`` flag already folds in the
    override (i.e. with ``override=True + signer="<addr>"`` a critical
    compliance risk stops blocking — other conditions still apply).
    """
    cfg = _load_sandbox_config(tenant_id)

    compliance_risk = _run_compliance_scan(tenant_id, cfg)
    reviewed, total = _count_rehearsal_reviewed(tenant_id)
    souls_saved = _count_required_souls(tenant_id)
    kb_chunks = _count_kb_chunks(tenant_id)

    blocking: list[str] = []
    warnings: list[str] = []

    # (a) compliance
    if compliance_risk == "critical":
        if override and signer:
            # overridden — record but don't block
            pass
        else:
            blocking.append(
                "compliance.risk_level=critical — override requires "
                "override=true + signer=<email>"
            )

    # (b) rehearsal — every dialog must be reviewed (no pending); total must
    # be > 0 (empty rehearsal is clearly "not reviewed at all").
    if total == 0:
        blocking.append("rehearsal.json missing or empty — no dialogs to review")
    elif reviewed < total:
        blocking.append(
            f"rehearsal.json has {total - reviewed}/{total} dialogs still pending review"
        )

    # (c) souls — 4 required (dream is M1 placeholder and not required here)
    if souls_saved < len(REQUIRED_SOUL_ROLES):
        missing = [
            role for role in REQUIRED_SOUL_ROLES
            if not (_sandbox_dir(tenant_id) / "souls" / f"{role}_soul.md").exists()
        ]
        blocking.append(
            f"missing soul files: {missing} "
            f"(expected {list(REQUIRED_SOUL_ROLES)})"
        )

    # (d) KB chunks — warning only
    if kb_chunks < KB_CHUNK_WARNING_THRESHOLD:
        warnings.append(
            f"kb.db has only {kb_chunks} chunks "
            f"(recommended ≥ {KB_CHUNK_WARNING_THRESHOLD})"
        )

    return GateResult(
        passed=not blocking,
        compliance_risk=compliance_risk,
        rehearsal_reviewed=reviewed,
        rehearsal_total=total,
        souls_saved=souls_saved,
        kb_chunks=kb_chunks,
        blocking_reasons=blocking,
        warnings=warnings,
        override=override,
        signer=signer,
    )


# ---------------------------------------------------------------------------
# plugin.yaml + README generation
# ---------------------------------------------------------------------------

def _plugin_yaml_text(tenant_id: str, brand_name: str, industry: str) -> str:
    """Render the minimum ``plugin.yaml`` the fork repo expects (§6.3)."""
    # Hand-rolled rather than importing pyyaml — keeps the module dependency
    # footprint small and output deterministic.
    desc = f"Tenant plugin for {brand_name or tenant_id} ({industry or 'general'})"
    return (
        f"name: {tenant_id}\n"
        "version: 1.0.0\n"
        f"description: {desc}\n"
        "mode: production\n"
        "mcp_tools: []\n"
        "http_routes: []\n"
    )


def _fork_local_config_yaml_text(tenant_id: str) -> str:
    """Render the exact ``.autoservice/config.local.yaml`` body that a
    tenant fork must carry (T8B.2, spec §3.4).

    Two required keys:

    - ``deployment_mode: tenant`` — flips ``get_deployment_mode()`` at
      startup to the tenant-mode branch (spec §3.1).
    - ``tenant_id: <tid>`` — resolves ``tenant_root()`` and scopes
      middleware routing (spec §3.2/§3.3).

    Without both, the fork refuses to boot (assert in ``bootstrap``).

    ``tenant_id`` is validated against a conservative identifier regex
    (``[A-Za-z0-9_][A-Za-z0-9_\\-]*``) — prevents yaml-injection and
    matches the fork repo naming constraint.
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    stripped = tenant_id.strip()
    if not _VALID_TENANT_ID_RE.match(stripped):
        raise ValueError(
            f"tenant_id {stripped!r} is not a valid identifier — "
            f"must match {_VALID_TENANT_ID_RE.pattern}"
        )
    return (
        "deployment_mode: tenant\n"
        f"tenant_id: {stripped}\n"
    )


def _readme_text(tenant_id: str, cfg: dict) -> str:
    """Render the plugin README shipped inside the tarball."""
    brand = cfg.get("brand_name") or tenant_id
    industry = cfg.get("industry") or "general"
    channels = cfg.get("channels") or []
    created = cfg.get("created_at") or _now_iso()
    return (
        f"# {brand} — AutoService Tenant Plugin\n"
        "\n"
        f"- tenant_id: `{tenant_id}`\n"
        f"- industry: `{industry}`\n"
        f"- channels: `{', '.join(channels) if channels else '(none)'}`\n"
        f"- created_at: `{created}`\n"
        f"- published_at: `{_now_iso()}`\n"
        "\n"
        "This directory is produced by Master's `/api/onboard/publish`\n"
        "and meant to live under `plugins/<tenant_id>/` inside a tenant\n"
        "fork of AutoService.\n"
        "\n"
        "See the companion `_PUBLISH_RUNBOOK.md` (in the same publish\n"
        "directory) for manual deployment steps.\n"
    )


# ---------------------------------------------------------------------------
# Tarball build
# ---------------------------------------------------------------------------

def build_publish_archive(tenant_id: str) -> Path:
    """Build the publish tarball and return its path.

    The tarball unpacks into fork-shape (``plugins/<tid>/...``) so that
    ``tar -xzf <artifact> -C <fork-repo-root>/`` drops it into place.

    Contents (§6.3)::

        plugins/<tid>/
          plugin.yaml
          config.json                 (copy of sandbox config)
          souls/*.md                  (all available, including dream)
          souls/_generation_meta.yaml (if present)
          kb/kb.db                    (if present)
          rehearsal_baseline.json     (copy of sandbox rehearsal.json)
          README.md                   (auto-generated)
    """
    PUBLISHED_ROOT.mkdir(parents=True, exist_ok=True)

    sandbox = _sandbox_dir(tenant_id)
    if not sandbox.exists():
        raise FileNotFoundError(
            f"sandbox directory missing for tenant {tenant_id!r}: {sandbox}"
        )

    cfg = _load_sandbox_config(tenant_id)
    ts = _timestamp()
    archive_path = PUBLISHED_ROOT / f"tenant_{tenant_id}_publish_{ts}.tar.gz"

    def _arcname(rel: str) -> str:
        # tarfile uses forward slashes regardless of host OS for portability.
        return f"plugins/{tenant_id}/{rel}"

    with tarfile.open(archive_path, "w:gz") as tar:
        # plugin.yaml (auto-generated)
        yaml_bytes = _plugin_yaml_text(
            tenant_id,
            cfg.get("brand_name", ""),
            cfg.get("industry", ""),
        ).encode("utf-8")
        _add_bytes(tar, _arcname("plugin.yaml"), yaml_bytes)

        # config.json (verbatim)
        cfg_path = sandbox / "config.json"
        tar.add(str(cfg_path), arcname=_arcname("config.json"))

        # souls/* — every .md and _generation_meta.yaml if present
        souls_dir = sandbox / "souls"
        if souls_dir.exists():
            for p in sorted(souls_dir.iterdir()):
                if p.is_file() and (p.suffix in {".md", ".yaml", ".yml"}):
                    tar.add(str(p), arcname=_arcname(f"souls/{p.name}"))

        # kb/kb.db
        kb_db = sandbox / "kb" / "kb.db"
        if kb_db.exists():
            tar.add(str(kb_db), arcname=_arcname("kb/kb.db"))

        # rehearsal_baseline.json (renamed from sandbox rehearsal.json)
        rehearsal = sandbox / "rehearsal.json"
        if rehearsal.exists():
            tar.add(
                str(rehearsal),
                arcname=_arcname("rehearsal_baseline.json"),
            )

        # README.md (auto-generated)
        readme_bytes = _readme_text(tenant_id, cfg).encode("utf-8")
        _add_bytes(tar, _arcname("README.md"), readme_bytes)

    return archive_path


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    """Add an in-memory byte payload as a tar entry (small helper)."""
    import io

    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Publish record + runbook
# ---------------------------------------------------------------------------

def write_publish_record(
    tenant_id: str,
    archive_path: Path,
    gate: GateResult,
    *,
    archived_to: Path | None = None,
    runbook_path: Path | None = None,
) -> Path:
    """Write ``.autoservice/published/<tid>.json`` and return its path."""
    PUBLISHED_ROOT.mkdir(parents=True, exist_ok=True)
    record_path = _published_record_path(tenant_id)
    body = {
        "tenant_id": tenant_id,
        "published_at": _now_iso(),
        "artifact": str(archive_path),
        "artifact_sha256": _sha256_of_file(archive_path),
        "runbook": str(runbook_path) if runbook_path else None,
        "source_sandbox_archived_to": (
            str(archived_to) if archived_to else None
        ),
        "status": "awaiting_fork",
        "pre_publish_checks": gate.to_record(),
    }
    record_path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return record_path


def write_runbook(tenant_id: str, archive_path: Path) -> Path:
    """Emit the manual fork-and-deploy runbook (§6.5 + spec §3.4 fix).

    Step ordering matters — the fork refuses to boot without
    ``.autoservice/config.local.yaml``, so the "Write config.local.yaml"
    step MUST appear between "Extract content" and "Verify".  Tests
    pin this ordering explicitly (``test_runbook_config_step_ordering``).
    """
    PUBLISHED_ROOT.mkdir(parents=True, exist_ok=True)
    runbook_path = PUBLISHED_ROOT / f"{tenant_id}_PUBLISH_RUNBOOK.md"
    timestamp = _now_iso()
    # Hand-rolled yaml body (T8B.2) — same source as what
    # `_fork_local_config_yaml_text` returns, so tests can assert the
    # runbook snippet matches the helper output line-for-line.
    config_yaml = _fork_local_config_yaml_text(tenant_id)
    body = f"""# Tenant {tenant_id} Publish Runbook

Generated by /api/onboard/publish on {timestamp}.

Artifact: `{archive_path}`

## Manual steps

1. **Fork main repo**:

   ```bash
   gh repo fork ezagent42/AutoService --fork-name AutoService-{tenant_id}
   ```

2. **Clone**:

   ```bash
   git clone git@github.com:<your>/AutoService-{tenant_id}.git
   cd AutoService-{tenant_id}
   ```

3. **Extract content**:

   ```bash
   tar -xzf {archive_path} -C .
   ```

   This drops the plugin under `plugins/{tenant_id}/`.

4. **Write `.autoservice/config.local.yaml`** (required — fork boot asserts
   `deployment_mode` + `tenant_id`, spec §3.1 / §3.4):

   ```bash
   mkdir -p .autoservice
   cat > .autoservice/config.local.yaml <<'EOF'
{config_yaml.rstrip()}
EOF
   ```

   ⚠️ **Overwrite warning**: `cat > ...` replaces any existing
   `.autoservice/config.local.yaml`. If you have already customized it
   (e.g. cc_pool tuning, Claude endpoints), merge manually — copy the two
   lines above into the existing file instead of overwriting.

5. **Verify**:

   ```bash
   make check
   make run-web
   ```

6. **Smoke test**:

   Visit `http://localhost:8000/chat` (fork is single-tenant — **no**
   `/tenant/<tenant_id>/` prefix).

7. **Deploy** per infra docs.

   ⚠️ **HTTPS required**: production deployments MUST terminate TLS.
   Magic-link auth tokens transit as cookies; plain HTTP leaks them to
   any network observer (spec §5.5 / §9 risk row). Configure your
   reverse proxy / load balancer to redirect HTTP → HTTPS and set
   `Secure; HttpOnly` on the session cookie.

---

*This file is auto-generated. Re-running `/api/onboard/publish` on the
same tenant will overwrite it.*
"""
    runbook_path.write_text(body, encoding="utf-8")
    return runbook_path


# ---------------------------------------------------------------------------
# Freeze + archive + unfreeze
# ---------------------------------------------------------------------------

_FROZEN_STATUS = "published_pending_fork"
_ARCHIVED_STATUS = "archived"
_SANDBOX_STATUS = "sandbox"


def _update_status(cfg_path: Path, status: str) -> dict:
    """Rewrite ``cfg_path`` with a new ``status`` value and return the cfg."""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["status"] = status
    cfg_path.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cfg


def freeze_sandbox(tenant_id: str) -> dict:
    """Flip sandbox config.status → ``published_pending_fork`` (§7.1).

    Does **not** change FS permissions — write-path checks elsewhere must
    inspect ``config.status`` and refuse when ≠ ``"sandbox"``.
    """
    cfg_path = _sandbox_dir(tenant_id) / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"sandbox config missing for tenant {tenant_id!r}: {cfg_path}"
        )
    return _update_status(cfg_path, _FROZEN_STATUS)


def archive_sandbox(tenant_id: str, *, ts: str | None = None) -> Path:
    """Move ``.autoservice/sandbox/<tid>/`` → ``.autoservice/archived/<tid>_<ts>/``.

    The moved config.json gets ``status=archived`` written in place (§7.2).
    """
    src = _sandbox_dir(tenant_id)
    if not src.exists():
        raise FileNotFoundError(
            f"sandbox dir missing for tenant {tenant_id!r}: {src}"
        )
    stamp = ts or _timestamp()
    dest = _archived_root_for(tenant_id, stamp)
    ARCHIVED_ROOT.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # extremely unlikely but deterministic: append a counter
        suffix = 1
        while True:
            alt = Path(f"{dest}_{suffix}")
            if not alt.exists():
                dest = alt
                break
            suffix += 1
    shutil.move(str(src), str(dest))

    archived_cfg = dest / "config.json"
    if archived_cfg.exists():
        _update_status(archived_cfg, _ARCHIVED_STATUS)
    return dest


def unfreeze(tenant_id: str, reason: str) -> dict:
    """Reverse freeze + archive (§7.3).

    Finds the most recent ``.autoservice/archived/<tid>_<ts>/`` and moves
    it back to ``.autoservice/sandbox/<tid>/``, then rewrites status to
    ``"sandbox"``.  Returns a summary dict (same shape the HTTP handler
    wraps in JSON).

    Raises ``FileNotFoundError`` when no archive exists (or if a live
    sandbox already occupies the destination — caller should inspect the
    error message).
    """
    if not reason or not reason.strip():
        raise ValueError("unfreeze requires a non-empty 'reason'")

    dest = _sandbox_dir(tenant_id)
    if dest.exists():
        raise FileExistsError(
            f"cannot unfreeze {tenant_id!r}: sandbox already exists at "
            f"{dest}; remove or rename first"
        )

    archives = _list_archives_for(tenant_id)
    if not archives:
        raise FileNotFoundError(
            f"no archived sandbox found for tenant {tenant_id!r} "
            f"under {ARCHIVED_ROOT}"
        )
    # Newest last — mtime-ordered inside _list_archives_for.
    src = archives[-1]

    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    restored_cfg = dest / "config.json"
    if restored_cfg.exists():
        _update_status(restored_cfg, _SANDBOX_STATUS)

    # Also clear the publish record's "status" so downstream tools see
    # that this tenant is back in sandbox state.  We keep the record file
    # itself for audit history.
    record = _published_record_path(tenant_id)
    if record.exists():
        try:
            body = json.loads(record.read_text(encoding="utf-8"))
            body["status"] = "unfrozen"
            body["unfrozen_at"] = _now_iso()
            body["unfreeze_reason"] = reason.strip()
            record.write_text(
                json.dumps(body, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "unfreeze: failed to update publish record for %s: %s",
                tenant_id,
                exc,
            )

    return {
        "tenant_id": tenant_id,
        "status": _SANDBOX_STATUS,
        "restored_from": str(src),
        "restored_to": str(dest),
        "reason": reason.strip(),
    }


def _list_archives_for(tenant_id: str) -> list[Path]:
    """Return archive directories for a tenant, ordered by mtime asc."""
    if not ARCHIVED_ROOT.exists():
        return []
    prefix = f"{tenant_id}_"
    candidates = [
        p for p in ARCHIVED_ROOT.iterdir()
        if p.is_dir() and p.name.startswith(prefix)
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def publish(
    tenant_id: str,
    *,
    override: bool = False,
    signer: str | None = None,
    fork_creator: ForkCreator | None = None,
) -> dict:
    """End-to-end publish for ``tenant_id``.

    Returns a dict with keys ``status``, ``gate``, ``artifact``, ``runbook``,
    ``record``, ``archived_to``.

    When the gate blocks and the caller did not supply a valid override,
    returns ``{"status": "blocked", "gate": {...}}`` with the detail so
    the HTTP layer can surface a 409.
    """
    gate = check_publish_gate(tenant_id, override=override, signer=signer)
    if not gate.passed:
        return {
            "status": "blocked",
            "gate": asdict(gate),
        }

    creator = fork_creator or LocalTarballForkCreator()

    # 1. Build the tarball.
    artifact_path = build_publish_archive(tenant_id)

    # 2. Delegate to ForkCreator — M1 just writes the runbook and wraps.
    fork_result = creator.create(tenant_id, artifact_path)

    # 3. Freeze sandbox config before we move it.
    freeze_sandbox(tenant_id)

    # 4. Physically archive the sandbox directory.
    archived_to = archive_sandbox(tenant_id)

    # 5. Persist record AFTER archive so the path is correct.
    record_path = write_publish_record(
        tenant_id,
        artifact_path,
        gate,
        archived_to=archived_to,
        runbook_path=fork_result.runbook_path,
    )

    return {
        "status": "published",
        "tenant_id": tenant_id,
        "artifact": str(artifact_path),
        "artifact_sha256": _sha256_of_file(artifact_path),
        "runbook": str(fork_result.runbook_path),
        "record": str(record_path),
        "archived_to": str(archived_to),
        "gate": asdict(gate),
    }
