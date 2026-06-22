# Git Task Helper

## Purpose

`git-task` is a small local Python utility for starting work on ticket-based Git branches.

It helps with the repetitive parts of the workflow:

- Detect the target Git repository.
- Detect the base branch.
- Read the Jira issue summary and issue type.
- Create a correctly named local branch.
- Move the Jira ticket to `In Progress`.
- Add a Jira comment with the generated branch name.
- Print the push command.

The tool does not push branches, create pull requests, delete anything, or run destructive Git commands.

## Requirements

You need:

- Python 3
- Git
- Jira Cloud account
- Jira API token
- Permission to browse Jira issues
- Permission to transition Jira issues
- Permission to add Jira comments

Python dependencies are listed in `requirements.txt`:

```bash
python3 -m pip install -r requirements.txt
```

The Python implementation uses:

- `jira` for Jira operations

Git operations use the installed `git` command directly.

It does not require `curl` or `jq`.

## Installation

Copy the script to a directory on your `PATH` and make it executable:

```bash
mkdir -p ~/bin
cp git-task.py ~/bin/git-task
chmod +x ~/bin/git-task
```

Ensure `~/bin` is in your `PATH`. For example, add this to `~/.zshrc` or `~/.bashrc`:

```bash
export PATH="$HOME/bin:$PATH"
```

## Jira Configuration

Set Jira credentials through environment variables:

```bash
export JIRA_BASE_URL="https://example.atlassian.net"
export JIRA_EMAIL="user@example.com"
export JIRA_API_TOKEN="local-api-token"
```

Do not commit Jira tokens, credentials, or personal configuration into the repository. Keep them in a local shell profile, password manager, or approved secret store.

## Git Configuration

You can use Git config to customize repository-specific behavior.

Example `~/.gitconfig`:

```ini
[task "cloud"]
	baseBranch = main
	jiraTransition = In Progress
	addComment = true

[task]
	defaultType = feature
```

Supported keys:

- `task.<repo-name>.baseBranch`: Base branch to create work branches from.
- `task.<repo-name>.jiraTransition`: Jira transition target. Defaults to `In Progress`.
- `task.<repo-name>.addComment`: Set to `false` to disable Jira comments by default.
- `task.defaultType`: Fallback branch type. Defaults to `feature`.

If `baseBranch` is not configured, the helper tries:

1. `origin/HEAD`
2. `origin/main`
3. `origin/master`

## Branch Naming

Branches use this format:

```text
<type>/<ticket-key>-<slugified-title>
```

Example:

```text
feature/DEVOPS-123-add-terraform-validation
```

The title is lowercased and converted into a simple URL-safe slug.

## Branch Type Mapping

By default, Jira issue type controls the branch prefix:

| Jira issue type | Branch type |
| --- | --- |
| `Bug` | `bugfix` |
| `Story` | `feature` |
| `Task` | `feature` |
| `Improvement` | `feature` |
| `Incident` | `hotfix` |
| `Documentation` | `docs` |

Unknown issue types use `task.defaultType`, or `feature` if that config is not set.

You can override the branch type with `--type`.

## Usage

Standard workflow:

```bash
git-task DEVOPS-123
```

Use a manual title instead of the Jira summary:

```bash
git-task DEVOPS-123 "add terraform validation"
```

Override the branch type:

```bash
git-task --type docs DEVOPS-123
```

Skip Jira completely:

```bash
git-task --no-jira DEVOPS-123 "add terraform validation"
```

Preview without changing Git or Jira:

```bash
git-task --dry-run DEVOPS-123
```

Open the Jira issue after normal processing:

```bash
git-task --open DEVOPS-123
```

Read Jira but do not transition the ticket:

```bash
git-task --no-transition DEVOPS-123
```

Read Jira but do not add a comment:

```bash
git-task --no-comment DEVOPS-123
```

## Dry Run Mode

`--dry-run` does not mutate Git, Jira, or the browser.

In dry-run mode, the helper may read local Git state, read Git config, read Jira issue data, and compute the branch name.

It will not:

- Fetch remote refs
- Create a branch
- Check out a branch
- Transition the Jira ticket
- Add a Jira comment
- Open the browser, even if `--open` is passed

Dry-run output includes:

- Repository name
- Ticket key
- Summary
- Issue type
- Base branch
- New branch
- Jira URL when Jira is enabled
- Planned transition
- Planned comment

## No Jira Mode

`--no-jira` skips all Jira API calls.

Because Jira is not used to read the summary, a manual title is required:

```bash
git-task --no-jira DEVOPS-123 "add terraform validation"
```

In no-Jira mode:

- The manual title is used for the branch slug.
- The branch type defaults to `task.defaultType` or `feature`.
- `--type` still overrides the branch type.
- No Jira transition or comment is attempted.

## Failure Behavior

Fatal errors stop the command with a non-zero exit code.

Examples:

- Command is run outside a Git repository.
- No `origin` remote exists.
- Required Jira environment variables are missing.
- Jira issue cannot be fetched.
- Base branch cannot be detected.
- Local branch already exists.
- Branch creation fails.

If the local branch is created successfully but a Jira transition or comment fails, the helper keeps the branch in place and prints manual follow-up instructions.

For example, it may tell you to:

- Move the ticket to `In Progress` manually.
- Add this comment manually: `Started work on branch <branch-name>`.

The final push command is still printed when possible.

## Troubleshooting

- **Missing Python package**: Run `python3 -m pip install -r requirements.txt`.
- **Jira credentials missing**: Set `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`.
- **Jira API returns 401 or 403**: Check that your email and API token are valid.
- **Jira transition not found**: The target transition may not be available from the ticket's current status.
- **Branch already exists**: Check out the existing branch or choose a different title/type.
- **No `origin` remote**: Add or rename the expected remote to `origin`.
- **Base branch cannot be detected**: Configure `task.<repo>.baseBranch`, or make sure `origin/HEAD`, `origin/main`, or `origin/master` exists.

## Safety Notes

- The helper creates only a local branch.
- It does not push automatically.
- It does not create pull requests.
- It does not delete branches.
- It does not run destructive Git commands.
- Jira mutations can be disabled with `--no-transition` and `--no-comment`.
- Use `--dry-run` when checking configuration.
