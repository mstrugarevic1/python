#!/usr/bin/env python3
"""Create a local Git branch for a Jira ticket."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TRANSITION = "In Progress"
DEFAULT_TYPE = "feature"

# Jira issue types are normalized to lowercase before lookup.
ISSUE_TYPE_TO_BRANCH_TYPE = {
    "bug": "bugfix",
    "story": "feature",
    "task": "feature",
    "improvement": "feature",
    "incident": "hotfix",
    "documentation": "docs",
}


@dataclass(frozen=True)
class Config:
    base_branch: str | None
    transition: str
    add_comment: bool
    default_type: str


def die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return slug.strip("-")


def parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    print(f"Warning: Invalid boolean Git config value '{value}', using {default}.", file=sys.stderr)
    return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="git-task",
        description="A Jira-aware Git workflow helper to start work on a ticket.",
    )
    parser.add_argument("--type", dest="type_override", help="Override branch type.")
    parser.add_argument("--no-jira", action="store_true", help="Skip all Jira API calls.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without mutating Git or Jira.",
    )
    parser.add_argument("--open", action="store_true", help="Open the Jira issue after processing.")
    parser.add_argument(
        "--no-transition",
        action="store_true",
        help="Read Jira but do not move the ticket.",
    )
    parser.add_argument(
        "--no-comment",
        action="store_true",
        help="Read Jira but do not add a comment.",
    )
    parser.add_argument("ticket", help="Jira ticket key, for example DEVOPS-123.")
    parser.add_argument("manual_title", nargs="?", help="Manual title override.")
    return parser.parse_args()


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(["git", *args], text=True, capture_output=True)
    except FileNotFoundError:
        die("Git is not installed or not on PATH.")
    if check and result.returncode:
        die(result.stderr.strip() or f"Git command failed: git {' '.join(args)}")
    return result


def config_value(key: str) -> str | None:
    result = run_git("config", "--get", key, check=False)
    return result.stdout.strip() or None


def load_config(repo_name: str) -> Config:
    default_type = config_value("task.defaultType") or DEFAULT_TYPE
    transition = config_value(f"task.{repo_name}.jiraTransition") or DEFAULT_TRANSITION
    base_branch = config_value(f"task.{repo_name}.baseBranch")
    add_comment_raw = config_value(f"task.{repo_name}.addComment")

    return Config(
        base_branch=base_branch,
        transition=transition,
        add_comment=parse_bool(add_comment_raw, default=True),
        default_type=default_type,
    )


def detect_base_branch(config: Config, repo_name: str) -> str:
    if config.base_branch:
        return config.base_branch

    origin_head = run_git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if origin_head.returncode == 0:
        return origin_head.stdout.strip().removeprefix("origin/")

    for name in ("main", "master"):
        if run_git("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{name}", check=False).returncode == 0:
            return name

    die(f"Could not detect base branch. Set one using: git config task.{repo_name}.baseBranch <branch>")


def load_jira_client() -> Any:
    base_url = os.environ.get("JIRA_BASE_URL")
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")

    missing = [
        name
        for name, value in {
            "JIRA_BASE_URL": base_url,
            "JIRA_EMAIL": email,
            "JIRA_API_TOKEN": token,
        }.items()
        if not value
    ]
    if missing:
        die(f"Jira environment variables are not set. Missing: {', '.join(missing)}.")

    try:
        from jira import JIRA, JIRAError
    except ImportError:
        die("Missing Python package 'jira'. Install it with: python3 -m pip install jira")

    try:
        return JIRA(server=base_url, basic_auth=(email, token))
    except JIRAError as exc:
        die(f"Failed to create Jira client: {jira_error_message(exc)}")


def jira_error_message(exc: Exception) -> str:
    """Return a compact message for jira.JIRAError and ordinary exceptions."""
    status = getattr(exc, "status_code", None)
    text = getattr(exc, "text", None)
    if status and text:
        return f"HTTP {status}: {text}"
    if status:
        return f"HTTP {status}"
    return str(exc)


def load_issue(jira_client: Any, ticket: str) -> tuple[Any, str, str]:
    try:
        issue = jira_client.issue(ticket)
    except Exception as exc:
        die(f"Failed to fetch Jira ticket {ticket}: {jira_error_message(exc)}")

    summary = getattr(issue.fields, "summary", None)
    issue_type_obj = getattr(issue.fields, "issuetype", None)
    issue_type = getattr(issue_type_obj, "name", None)

    if not summary or not issue_type:
        die("Could not read Jira summary or issue type.")

    return issue, summary, issue_type


def create_branch(branch_name: str, base_branch: str) -> None:
    if run_git("show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}", check=False).returncode == 0:
        die(f"Local branch '{branch_name}' already exists.")

    base_ref = f"refs/remotes/origin/{base_branch}"
    if run_git("show-ref", "--verify", "--quiet", base_ref, check=False).returncode:
        die(f"Base branch 'origin/{base_branch}' was not found.")
    run_git("switch", "--create", branch_name, f"origin/{base_branch}")


def find_transition(jira_client: Any, issue: Any, transition_name: str) -> dict[str, Any] | None:
    transitions = jira_client.transitions(issue)
    transition_name_lower = transition_name.lower()
    # Jira transition names are user-facing labels, so match them
    # case-insensitively to avoid needless workflow friction.
    for transition in transitions:
        if transition.get("name", "").lower() == transition_name_lower:
            return transition
    return None


def print_jira_manual_steps(ticket: str, transition: str, branch_name: str, need_transition: bool, need_comment: bool) -> None:
    print("")
    print("Manual Jira follow-up needed:")
    if need_transition:
        print(f"- Move {ticket} to '{transition}' manually.")
    if need_comment:
        print(f"- Add this comment manually: Started work on branch {branch_name}")


def transition_issue(jira_client: Any, issue: Any, ticket: str, transition_name: str, branch_name: str) -> bool:
    try:
        transition = find_transition(jira_client, issue, transition_name)
        if transition is None:
            print(f"Error: Transition '{transition_name}' not found for current issue state.", file=sys.stderr)
            print_jira_manual_steps(ticket, transition_name, branch_name, need_transition=True, need_comment=False)
            return False

        jira_client.transition_issue(issue, transition["id"])
        print(f"Jira ticket moved to '{transition_name}'.")
        return True
    except Exception as exc:
        # At this point the local branch may already exist. Do not roll it back;
        # report exactly what the user still needs to do in Jira.
        print(f"Error: Failed to transition Jira ticket: {jira_error_message(exc)}", file=sys.stderr)
        print_jira_manual_steps(ticket, transition_name, branch_name, need_transition=True, need_comment=False)
        return False


def add_comment(jira_client: Any, issue: Any, ticket: str, transition_name: str, branch_name: str) -> bool:
    comment = f"Started work on branch {branch_name}"
    try:
        jira_client.add_comment(issue, comment)
        print("Comment added to Jira ticket.")
        return True
    except Exception as exc:
        # Commenting is useful but not worth discarding a successfully created
        # local branch. Tell the user the exact comment to add manually.
        print(f"Error: Failed to add Jira comment: {jira_error_message(exc)}", file=sys.stderr)
        print_jira_manual_steps(ticket, transition_name, branch_name, need_transition=False, need_comment=True)
        return False


def main() -> int:
    args = parse_args()

    if args.no_jira and not args.manual_title:
        die("Manual title is required when using --no-jira mode.")

    repo_root = Path(run_git("rev-parse", "--show-toplevel").stdout.strip())
    repo_name = repo_root.name
    run_git("remote", "get-url", "origin")
    config = load_config(repo_name)

    # A fetch updates remote-tracking refs, so it is intentionally skipped in
    # dry-run mode even though normal mode fetches before branch detection.
    if not args.dry_run:
        print("Fetching latest remote refs...")
        run_git("fetch", "origin", "--prune")

    base_branch = detect_base_branch(config, repo_name)

    jira_client = None
    issue = None
    jira_url = None

    if args.no_jira:
        summary = args.manual_title
        issue_type = "N/A"
        branch_type = args.type_override or config.default_type
    else:
        jira_client = load_jira_client()
        print(f"Fetching Jira issue {args.ticket}...")
        issue, jira_summary, issue_type = load_issue(jira_client, args.ticket)
        summary = args.manual_title or jira_summary
        branch_type = args.type_override or ISSUE_TYPE_TO_BRANCH_TYPE.get(issue_type.lower(), config.default_type)
        jira_url = f"{os.environ['JIRA_BASE_URL'].rstrip('/')}/browse/{args.ticket}"

    slug = slugify(summary)
    if not slug:
        die("Generated branch title slug is empty.")

    branch_name = f"{branch_type}/{args.ticket}-{slug}"
    should_transition = not args.no_jira and not args.no_transition
    should_comment = not args.no_jira and not args.no_comment and config.add_comment

    print(f"\nRepository:  {repo_name}")
    print(f"Ticket:      {args.ticket}")
    print(f"Summary:     {summary}")
    print(f"Issue type:  {issue_type}")
    print(f"Base branch: {base_branch}")
    print(f"New branch:  {branch_name}")
    if jira_url:
        print(f"Jira URL:    {jira_url}")
    print("")

    if args.dry_run:
        print(f"[Dry Run] Would create branch {branch_name} from origin/{base_branch}")
        if should_transition:
            print(f"[Dry Run] Would transition ticket to '{config.transition}'")
        if should_comment:
            print("[Dry Run] Would add comment to ticket")
        print(f"[Dry Run] Final push command would be:\ngit push -u origin {branch_name}")
        print("[Dry Run] Browser will not be opened in dry-run mode.\n[Dry Run] Finished.")
        return 0

    print("Creating branch...")
    create_branch(branch_name, base_branch)
    print("Branch created successfully.")

    jira_problem = False
    if jira_client and issue:
        if should_transition:
            jira_problem = not transition_issue(
                jira_client, issue, args.ticket, config.transition, branch_name
            )

        if should_comment:
            jira_problem = not add_comment(
                jira_client, issue, args.ticket, config.transition, branch_name
            ) or jira_problem

        if args.open:
            print("Opening Jira issue...")
            webbrowser.open(jira_url)

    print("")
    print("Next:")
    print(f"git push -u origin {branch_name}")

    if jira_problem:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
