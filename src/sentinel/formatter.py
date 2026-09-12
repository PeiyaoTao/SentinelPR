"""
Terminal Formatter for SentinelPR.
Provides ANSI color-coded reporting (Red for severe errors, Yellow for warnings, Green for clean)
and terminal-friendly clickable file jump links.
"""

import os
import sys
from typing import List

from sentinel.state import ConsolidatedReport, Finding, Severity

# Enable ANSI virtual terminal processing on Windows
if sys.platform == "win32":
    os.system("")

# ANSI Escape Sequences (No Emojis)
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_GREEN = "\033[92m"
COLOR_CYAN = "\033[96m"
COLOR_GRAY = "\033[90m"


def color_severity(severity: Severity) -> str:
    """Returns color-coded severity tag."""
    val = severity.value
    if severity in [Severity.CRITICAL, Severity.HIGH]:
        return f"{COLOR_RED}{COLOR_BOLD}[{val}]{COLOR_RESET}"
    elif severity in [Severity.MEDIUM, Severity.LOW]:
        return f"{COLOR_YELLOW}{COLOR_BOLD}[{val}]{COLOR_RESET}"
    else:
        return f"{COLOR_CYAN}[{val}]{COLOR_RESET}"


def make_clickable_link(file_path: str, line: int) -> str:
    """
    Formats path so modern terminals (VS Code, Windows Terminal, iTerm)
    allow Ctrl+Click to immediately jump to the line in the editor.
    """
    abs_path = os.path.abspath(file_path)
    rel_path = os.path.relpath(file_path) if os.path.exists(file_path) else file_path
    return f"{COLOR_CYAN}{COLOR_BOLD}{rel_path}:{line}{COLOR_RESET} {COLOR_GRAY}(file:///{abs_path.replace(os.sep, '/')}:{line}){COLOR_RESET}"


def print_colored_report(report: ConsolidatedReport, verified_findings: List[Finding]):
    """
    Renders terminal report with clear Red/Yellow/Green color markings
    and clickable line links.
    """
    print("\n" + "=" * 65)
    print(f"{COLOR_BOLD}SentinelPR Quality Gate Analysis{COLOR_RESET}")
    print("=" * 65)

    if not verified_findings:
        print(f"\n{COLOR_GREEN}{COLOR_BOLD}[CLEAN / PASS] No defects or bloat detected.{COLOR_RESET}")
        print(f"{COLOR_GREEN}Quality gate passed successfully.{COLOR_RESET}\n")
        return

    severe_count = sum(1 for f in verified_findings if f.severity in [Severity.CRITICAL, Severity.HIGH])
    warning_count = sum(1 for f in verified_findings if f.severity in [Severity.MEDIUM, Severity.LOW, Severity.SUGGESTION])

    print("\nOverview:")
    if severe_count > 0:
        print(f"  {COLOR_RED}{COLOR_BOLD}Severe Defects (Red)    : {severe_count}{COLOR_RESET}")
    else:
        print(f"  {COLOR_GREEN}Severe Defects (Red)    : 0{COLOR_RESET}")

    if warning_count > 0:
        print(f"  {COLOR_YELLOW}{COLOR_BOLD}Warnings / Bloat (Yellow): {warning_count}{COLOR_RESET}")
    else:
        print(f"  {COLOR_GREEN}Warnings / Bloat (Yellow): 0{COLOR_RESET}")

    print(f"  {COLOR_GRAY}Total Evaluated         : {report.total_findings_count}{COLOR_RESET}")
    print(f"  {COLOR_GRAY}Filtered by Critic Gate : {report.rejected_findings_count}{COLOR_RESET}")

    print("\nDetailed Findings:")
    print("-" * 65)

    for idx, finding in enumerate(verified_findings, 1):
        sev_badge = color_severity(finding.severity)
        link = make_clickable_link(finding.file_path, finding.start_line)

        print(f"\n{idx}. {sev_badge} {COLOR_BOLD}{finding.title}{COLOR_RESET}")
        print(f"   Jump to line : {link}")
        print(f"   Category     : {finding.category.value} | Zone: {finding.trust_zone.value}")
        print(f"   Explanation  : {finding.explanation}")

        if finding.suggested_fix:
            print(f"   {COLOR_GREEN}Suggested Fix:{COLOR_RESET}")
            for fix_line in finding.suggested_fix.splitlines():
                print(f"     {COLOR_GREEN}+ {fix_line}{COLOR_RESET}")

        if finding.critic_reasoning:
            print(f"   {COLOR_GRAY}Critic Verdict: {finding.critic_reasoning}{COLOR_RESET}")

    print("\n" + "=" * 65 + "\n")
