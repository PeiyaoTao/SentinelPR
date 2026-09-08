"""
Command Line Interface (CLI) for SentinelPR.
"""

import argparse
import os
import subprocess
import sys
from typing import Dict, Tuple

from sentinel.config import default_config
from sentinel.graph import review_pr


def get_git_diff_and_files(diff_command: list) -> Tuple[str, Dict[str, str]]:
    """Runs a git diff command and loads the post-change head files."""
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
        for path in changed_paths:
            if os.path.exists(path) and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        head_files[path] = f.read()
                except Exception:
                    pass

        return diff_text, head_files
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"Git error: {e.stderr}\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SentinelPR: Autonomous Code Reviewer & PR Quality Gate"
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Review uncommitted changes in current repository (git diff HEAD)",
    )
    parser.add_argument(
        "--branch",
        type=str,
        help="Target base branch to diff against (e.g. main, master)",
    )
    parser.add_argument(
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

    args = parser.parse_args()

    # Override config if CLI arguments passed
    if args.provider:
        default_config.provider = args.provider
    if args.model:
        default_config.fast_model = args.model
        default_config.frontier_model = args.model
    if args.base_url:
        default_config.base_url = args.base_url

    diff_text = ""
    head_files: Dict[str, str] = {}

    if args.git:
        diff_text, head_files = get_git_diff_and_files(["git", "diff", "HEAD"])
    elif args.branch:
        diff_text, head_files = get_git_diff_and_files(["git", "diff", f"{args.branch}...HEAD"])
    elif args.diff_file:
        if not os.path.exists(args.diff_file):
            sys.stderr.write(f"Error: Diff file '{args.diff_file}' not found.\n")
            sys.exit(1)
        with open(args.diff_file, "r", encoding="utf-8", errors="replace") as f:
            diff_text = f.read()
    else:
        # Default behavior: if inside a git repo, check git status / diff
        diff_text, head_files = get_git_diff_and_files(["git", "diff", "HEAD"])
        if not diff_text.strip():
            print("No uncommitted git changes found. Use --git, --branch <branch>, or --diff-file <path>.")
            print("Run 'python -m sentinel.harness.eval_suite' to execute the synthetic PR benchmark.")
            return

    if not diff_text.strip():
        print("Diff is empty. Nothing to review!")
        return

    print(f"Starting SentinelPR review (Provider: {default_config.provider}, Model: {default_config.fast_model})...")

    result = review_pr(diff=diff_text, head_files=head_files)
    report = result.get("consolidated_report")

    if report:
        print("\n" + report.summary_markdown)

        if report.inline_comments:
            print("\n### Inline Suggestions:")
            for comment in report.inline_comments:
                print(f"- {comment['path']}:{comment['line']}")

        if args.sarif:
            import json
            with open(args.sarif, "w", encoding="utf-8") as f:
                json.dump(report.sarif_json, f, indent=2)
            print(f"\nSARIF report exported to {args.sarif}")


if __name__ == "__main__":
    main()
