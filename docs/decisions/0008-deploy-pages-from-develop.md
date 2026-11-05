---
status: accepted
date: 2026-11-04
---

# Deploy the static editor from develop with GitHub Actions

## Context and problem statement

The repository has a working static editor and a manual Pages workflow. Publishing
should follow updates to `develop`, the repository's default branch. Pull requests
need to exercise the same build without replacing the public site.

## Decision drivers

- Publish the complete editor and Wasm assets from one verified build.
- Check pull requests without granting deployment permissions to their code.
- Keep manual redeployment available.
- Preserve GitHub Pages project-path support and exclude the browser test harness.

## Considered options

- Keep manual deployment only.
- Build and deploy every workflow event in one job.
- Validate pull requests and deploy develop through separate build and deploy jobs.

## Decision outcome

Use one workflow with push and pull-request triggers for `develop`, plus manual
dispatch. Its build job has read-only repository permissions and runs the Rust
core tests, TypeScript checks, frontend tests, and browser tests. It then rebuilds
the production site, checks that the browser test harness is absent, and opens
that exact build in a browser. The smoke test loads the editor and Wasm under the
Pages project path and round-trips an existing save before the artifact is uploaded.

Checkout does not retain Git credentials because the build does not need further
authenticated Git operations. CI rejects focused Playwright tests so an accidental
`test.only` cannot skip the browser suite. Failed browser tests retain their traces
and screenshots as a separate Actions artifact for seven days.

Only non-pull-request runs on `develop` upload a Pages artifact and enter the
deployment job. That job depends on the successful build, uses the `github-pages`
environment, and receives the Pages and OIDC write permissions. Repository Pages
settings use the GitHub Actions publishing source.

Serialize runs for each branch or pull request. Superseded pull-request checks
can be cancelled, while an active production deployment finishes. Keep action
versions pinned to the existing commit SHAs and Node dependencies locked through
`npm ci`. The Wasm CLI version continues to match the locked Rust dependency.

### Consequences

- Good, because pushes to the default branch publish without a separate manual run.
- Good, because failed checks leave the published site unchanged.
- Good, because pull-request builds cannot enter the deployment job.
- Bad, because every push to `develop` waits for the complete browser build and tests.
- Bad, because renaming the deployment branch requires updating workflow filters
  and any GitHub environment restrictions.

### Confirmation

Validate the workflow with actionlint and the repository's YAML checks. Verify
that GitHub Pages uses the workflow publishing source and that the deployment
environment permits `develop`. The existing static build and browser tests check
asset loading under `/gridiron-playbook/`. A remote run after pushing the workflow
confirms GitHub's artifact upload and Pages deployment.

## Pros and cons of the options

### Manual deployment only

- Good, because each publication is explicitly started.
- Bad, because publishing requires an extra action after every update.

### Build and deploy every event in one job

- Good, because the workflow has fewer jobs.
- Bad, because pull-request execution and deployment permissions share a job.
- Bad, because non-production branches could replace the public site.

### Separate validation and deployment

- Good, because deployment requires a successful build of the same revision.
- Good, because deployment permissions apply only to the publishing job.
- Bad, because the jobs must pass a production artifact between them.

## More information

This completes the Pages hosting setup for the static application in ADR 0006.

- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Configuring a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
