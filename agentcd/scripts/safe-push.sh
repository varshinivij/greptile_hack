#!/usr/bin/env bash
set -euo pipefail

remote="${1:-origin}"
branch="${2:-$(git branch --show-current)}"

if [[ -z "$branch" ]]; then
  echo "Could not determine current branch. Pass one explicitly: $0 <remote> <branch>" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not inside a git repository." >&2
  exit 1
fi

echo "Fetching $remote..."
git fetch "$remote"

if git rev-parse --verify "$remote/$branch" >/dev/null 2>&1; then
  echo "Pulling latest $remote/$branch with rebase and autostash..."
  git pull --rebase --autostash "$remote" "$branch"
else
  echo "Remote branch $remote/$branch does not exist yet. Skipping pull."
fi

echo "Checking that local branch can be pushed without rewriting remote history..."
if git rev-parse --verify "$remote/$branch" >/dev/null 2>&1; then
  remote_commit="$(git rev-parse "$remote/$branch")"
  local_commit="$(git rev-parse HEAD)"

  if ! git merge-base --is-ancestor "$remote_commit" "$local_commit"; then
    echo "Refusing to push: local HEAD does not contain $remote/$branch." >&2
    echo "Resolve by pulling/rebasing first, then rerun this script." >&2
    exit 1
  fi
fi

echo "Pushing $branch to $remote..."
git push "$remote" "$branch"
