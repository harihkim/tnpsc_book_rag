# Contributing

## Branch workflow

`main` is the source of truth. All feature and fix work lands there before it can be promoted.
`prod` is a deployment pointer and must contain only commits already present on `main`. Never
develop on `prod`, and never deploy a feature branch.

1. Update local `main` from `origin/main`.
2. Create a short-lived branch named `feat/<topic>`, `fix/<topic>`, or `chore/<topic>`.
3. Keep commits focused and use conventional commit subjects.
4. Open a pull request into `main`.
5. Require the `backend-quality` and `frontend-quality` checks to pass before merging.
6. Prefer squash merge for a noisy branch, or rebase/fast-forward when its commits are already
   clean.
7. Delete the remote feature branch after merge.

Direct pushes and force pushes to `main` should be disabled in the GitHub branch ruleset. Require
at least one approval when another maintainer is available, require conversation resolution, and
require the branch to be current before merge.

Promote an already-tested commit without creating a new merge commit:

```bash
git fetch origin
git merge-base --is-ancestor origin/prod origin/main
git push origin origin/main:prod
```

The ancestry check must pass. If `prod` has diverged, stop and reconcile it from `main`; never
force-push either protected branch.

## Deployment workflow

Production deployments must consume the selected commit on `prod`, ideally with a matching
release tag. Backend and frontend deployments should use separate protected GitHub environments
and separate workflows:

- backend: Heroku release from the selected `prod` commit;
- frontend: Cloudflare Pages deployment from the same selected commit;
- extraction worker: intentionally separate and deployed only after its runtime strategy is
  decided.

Until those protected environments and repository secrets exist, deployments remain explicit
CLI operations. Record the deployed commit SHA in the release notes.
