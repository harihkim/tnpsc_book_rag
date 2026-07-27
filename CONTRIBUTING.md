# Contributing

## Branch workflow

`main` is the only release branch and must remain deployable. Do not deploy long-lived
development branches.

1. Update local `main` from `origin/main`.
2. Create a short-lived branch named `feat/<topic>`, `fix/<topic>`, or `chore/<topic>`.
3. Keep commits focused and use conventional commit subjects.
4. Open a pull request into `main`.
5. Require `backend-ci` and `frontend-ci` to pass before merging.
6. Prefer squash merge for a noisy branch, or rebase/fast-forward when its commits are already
   clean.
7. Delete the remote feature branch after merge.

Direct pushes and force pushes to `main` should be disabled in the GitHub branch ruleset.
Require at least one approval when another maintainer is available, require conversation
resolution, and require the branch to be current before merge.

## Deployment workflow

Production deployments must consume a commit on `main`, ideally a tagged release. Backend and
frontend deployments should use separate protected GitHub environments and separate workflows:

- backend: Heroku release from the selected `main` commit;
- frontend: Cloudflare Pages deployment from the same selected commit;
- extraction worker: intentionally separate and deployed only after its runtime strategy is
  decided.

Until those protected environments and repository secrets exist, deployments remain explicit
CLI operations. Record the deployed commit SHA in the release notes.
