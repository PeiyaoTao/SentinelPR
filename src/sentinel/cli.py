"""
Command Line Interface (CLI) for SentinelPR.
"""

import argparse
import os
import subprocess
import sys
from typing import Dict, Optional, Tuple

from sentinel.config import default_config
from sentinel.graph import review_pr, review_repository
from sentinel.state import ReviewOutcome


def get_git_diff_and_files(diff_command: list, base_ref: Optional[str] = None) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """Runs a git diff command and loads immutable post-change and pre-change files."""
    try:
        diff_proc = subprocess.run(
            diff_command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        diff_text = diff_proc.stdout

        # Get list of changed files
        name_proc = subprocess.run(
            diff_command + ["--name-only"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        changed_paths = [p.strip() for p in name_proc.stdout.splitlines() if p.strip()]

        head_files: Dict[str, str] = {}
        base_files: Dict[str, str] = {}

        if base_ref:
            # Immutable commit snapshot resolution
            for path in changed_paths:
                h_proc = subprocess.run(
                    ["git", "show", f"HEAD:{path}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if h_proc.returncode == 0:
                    head_files[path] = h_proc.stdout

                b_proc = subprocess.run(
                    ["git", "show", f"{base_ref}:{path}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if b_proc.returncode == 0:
                    base_files[path] = b_proc.stdout
        else:
            # Working tree snapshot
            for path in changed_paths:
                if os.path.exists(path) and os.path.isfile(path):
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            head_files[path] = f.read()
                    except (OSError, UnicodeDecodeError) as e:
                        sys.stderr.write(f"Warning: Failed to read head file '{path}': {e}\n")
                # Attempt to read pre-change base file from HEAD
                b_proc = subprocess.run(
                    ["git", "show", f"HEAD:{path}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if b_proc.returncode == 0:
                    base_files[path] = b_proc.stdout

        return diff_text, head_files, base_files
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"Git error: {e.stderr}\n")
        sys.exit(3)


def _outcome_exit_code(outcome: ReviewOutcome) -> int:
    return {
        ReviewOutcome.CLEAN: 0, ReviewOutcome.CHANGES_REQUIRED: 1,
        ReviewOutcome.INCOMPLETE_REVIEW: 2, ReviewOutcome.INFRASTRUCTURE_FAILURE: 3,
    }[outcome]


def _export_report(report, markdown_path, sarif_path) -> None:
    import json
    from pathlib import Path
    if markdown_path:
        Path(markdown_path).write_text(report.summary_markdown, encoding="utf-8")
    if sarif_path:
        Path(sarif_path).write_text(json.dumps(report.sarif_json, indent=2), encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="SentinelPR: Autonomous Code Reviewer & PR Quality Gate"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--repo", nargs="?", const=".", metavar="PATH", help="Review an entire local repository or project directory (default: current directory)")
    modes.add_argument(
        "--git",
        action="store_true",
        help="Review uncommitted changes in current repository (git diff HEAD)",
    )
    modes.add_argument(
        "--branch",
        type=str,
        help="Target base branch to diff against (e.g. main, master)",
    )
    modes.add_argument(
        "--diff-file",
        type=str,
        help="Path to a unified .diff or .patch file to review",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["heuristics", "ollama", "openai", "gemini", "deepseek"],
        help="Select LLM provider (defaults to heuristics / AST rules)",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Model name (e.g. qwen2.5-coder:7b, gpt-4o-mini, deepseek-chat)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        help="API base URL (e.g. http://localhost:11434/v1 for Ollama)",
    )
    parser.add_argument(
        "--sarif",
        type=str,
        help="File path to export SARIF 2.1.0 report",
    )

    parser.add_argument("--markdown", metavar="PATH", help="Write the complete review as Markdown")

    parser.add_argument("--baseline", metavar="PATH", help="Compare repository quality findings with a saved baseline")
    parser.add_argument("--save-baseline", metavar="PATH", help="Save a complete repository quality review as a baseline")
    parser.add_argument("--checks", help="Comma-separated project checks or all: lint,types,tests,build,dependencies,secrets (requires --repo)")
    parser.add_argument("--check-image", default="sentinel-checks:local", help="Prepared offline validation image")
    parser.add_argument("--check-timeout", type=int, default=300, help="Timeout in seconds per validation tool")
    parser.add_argument("--requirements", default="requirements-audit.txt", help="Pinned audit requirements path relative to the repository")
    parser.add_argument("--no-llm-critic", action="store_true", help="Disable optional contextual model criticism; keep deterministic evidence checks")
    args = parser.parse_args()
    from sentinel.checks.models import CHECK_NAMES
    selected_checks = list(CHECK_NAMES) if args.checks == "all" else (args.checks.split(",") if args.checks else [])
    if args.checks and (args.repo is None or any(name not in CHECK_NAMES for name in selected_checks)):
        parser.error("--checks requires --repo and a valid comma-separated check selection")
    if args.check_timeout < 1:
        parser.error("--check-timeout must be positive")
    if (args.baseline or args.save_baseline) and args.repo is None:
        parser.error("Quality baselines require --repo")

    if args.no_llm_critic:
        default_config.llm_critic_enabled = False

    # Override config if CLI arguments passed
    if args.provider:
        default_config.provider = args.provider
    if args.model:
        default_config.fast_model = args.model
        default_config.frontier_model = args.model
    if args.base_url:
        default_config.base_url = args.base_url

    if args.repo is not None:
        try:
            result = review_repository(args.repo, baseline_path=args.baseline)
            report = result["consolidated_report"]
            if selected_checks:
                from sentinel.checks.runner import run_checks
                from sentinel.checks.report import attach_validation
                attach_validation(report, run_checks(args.repo, selected_checks, args.check_image, args.check_timeout, args.requirements))
            print(report.summary_markdown)
            _export_report(report, args.markdown, args.sarif)
            if args.save_baseline:
                from sentinel.quality.baseline import save_baseline
                save_baseline(report, args.save_baseline)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            sys.stderr.write(f"Repository review failed: {error}\n")
            sys.exit(3)
        sys.exit(_outcome_exit_code(report.review_outcome))

    diff_text = ""
    head_files: Dict[str, str] = {}
    base_files: Dict[str, str] = {}

    if args.git:
        diff_text, head_files, base_files = get_git_diff_and_files(["git", "diff", "HEAD"])
    elif args.branch:
        diff_text, head_files, base_files = get_git_diff_and_files(["git", "diff", f"{args.branch}...HEAD"], base_ref=args.branch)
    elif args.diff_file:
        if not os.path.exists(args.diff_file):
            sys.stderr.write(f"Error: Diff file '{args.diff_file}' not found.\n")
            sys.exit(3)
        with open(args.diff_file, "r", encoding="utf-8", errors="replace") as f:
            diff_text = f.read()

        from sentinel.agents.triage import parse_diff_hunks
        for hunk in parse_diff_hunks(diff_text):
            if os.path.exists(hunk.file_path) and os.path.isfile(hunk.file_path):
                try:
                    with open(hunk.file_path, "r", encoding="utf-8", errors="replace") as f:
                        head_files[hunk.file_path] = f.read()
                except (OSError, UnicodeDecodeError) as e:
                    sys.stderr.write(f"Warning: Failed to read diff target file '{hunk.file_path}': {e}\n")
            elif hunk.file_path not in head_files:
                import textwrap
                reconstructed_lines = []
                # Pad empty lines up to new_start - 1 so line numbers align
                for _ in range(max(0, hunk.new_start - 1)):
                    reconstructed_lines.append("")
                hunk_body = []
                for line in hunk.content.splitlines():
                    if line.startswith("@@") or line.startswith("-"):
                        continue
                    elif line.startswith("+"):
                        hunk_body.append(line[1:])
                    else:
                        hunk_body.append(line[1:] if line.startswith(" ") else line)
                dedented_body = textwrap.dedent("\n".join(hunk_body)).splitlines()
                head_files[hunk.file_path] = "\n".join(reconstructed_lines + dedented_body)
    else:
        # Default behavior: if inside a git repo, check git status / diff
        diff_text, head_files, base_files = get_git_diff_and_files(["git", "diff", "HEAD"])
        if not diff_text.strip():
            print("No uncommitted git changes found. Use --git, --branch <branch>, or --diff-file <path>.")
            print("Run 'python -m sentinel.harness.eval_suite' to execute the synthetic PR benchmark.")
            return

    if not diff_text.strip():
        print("Diff is empty. Nothing to review!")
        return

    print(f"Starting SentinelPR review (Provider: {default_config.provider}, Model: {default_config.fast_model})...")

    result = review_pr(diff=diff_text, head_files=head_files, base_files=base_files)
    report = result.get("consolidated_report")
    verified_findings = result.get("verified_findings", [])

    if report:
        from sentinel.formatter import print_colored_report
        print_colored_report(report, verified_findings)
        from sentinel.quality.render import render_quality
        print(render_quality(report.quality_review))

        _export_report(report, args.markdown, args.sarif)
        sys.exit(_outcome_exit_code(report.review_outcome))
    else:
        sys.stderr.write("Review completed with no report generated.\n")
        sys.exit(3)


if __name__ == "__main__":
    main()
