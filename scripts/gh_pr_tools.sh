#!/usr/bin/env bash
set -euo pipefail

# Simple helper for PR create / CI status / rerun using GitHub CLI (gh)
# Usage:
#   bash scripts/gh_pr_tools.sh create [-b branch]
#   bash scripts/gh_pr_tools.sh status [-b branch]
#   bash scripts/gh_pr_tools.sh rerun  [-b branch]
#   bash scripts/gh_pr_tools.sh retest [-b branch]  # posts "/retest" comment

function need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Error: $1 not found in PATH" >&2; exit 127; }
}

need gh
need git

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
cmd="${1:-}"
shift || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--branch)
      branch="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

function pr_number_for_branch() {
  # Returns PR number for the head branch if exists; empty otherwise
  gh pr view --head "$branch" --json number -q .number 2>/dev/null || true
}

function create_pr() {
  local prnum
  prnum=$(pr_number_for_branch)
  if [[ -n "$prnum" ]]; then
    echo "PR already exists: #$prnum"
    gh pr view --head "$branch" --web || true
    return 0
  fi
  echo "Creating PR from $branch -> main ..."
  gh pr create --fill --base main --head "$branch"
}

function ci_status() {
  echo "Latest workflow runs for branch=$branch"
  gh run list --branch "$branch" --limit 5 --json databaseId,headBranch,displayTitle,workflowName,status,conclusion,createdAt -q \
    '.[].|[.databaseId, .workflowName, .status, .conclusion, .createdAt] | @tsv' |
    awk -F"\t" '{ printf("run_id=%s  wf=%s  status=%s  conclusion=%s  at=%s\n", $1,$2,$3,$4,$5) }' || true
}

function ci_rerun() {
  # Prefer CI workflow; fallback to the latest run
  local run_id
  run_id=$(gh run list --branch "$branch" --workflow CI --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)
  if [[ -z "$run_id" ]]; then
    run_id=$(gh run list --branch "$branch" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)
  fi
  if [[ -z "$run_id" ]]; then
    echo "No workflow run found for branch $branch" >&2
    exit 1
  fi
  echo "Re-running workflow run_id=$run_id for branch=$branch ..."
  gh run rerun "$run_id"
}

function comment_retest() {
  local prnum
  prnum=$(pr_number_for_branch)
  if [[ -z "$prnum" ]]; then
    echo "No PR found for branch $branch" >&2
    exit 1
  fi
  echo "Commenting /retest on PR #$prnum ..."
  gh issue comment "$prnum" --body "/retest"
}

case "$cmd" in
  create) create_pr ;;
  status) ci_status ;;
  rerun)  ci_rerun  ;;
  retest) comment_retest ;;
  *) echo "Usage: $0 {create|status|rerun|retest} [-b branch]" >&2; exit 2;;
esac

