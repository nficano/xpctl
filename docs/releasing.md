# Releases

`xpctl` uses a single GitHub workflow for both automated and manual releases:

1. Pushes to `main` create a patch release automatically.
2. Manual annotated `v<version>` tags still publish through the same workflow.

## Requirements

- `debaser` installed locally
- push access to the target GitHub repository
- PyPI trusted publishing configured for `.github/workflows/release.yml`

## Automatic release flow

Every push to `main` that is not already a `Release v...` commit will:

- bump the patch version with `scripts/release.py`
- create the release commit and annotated tag
- push the commit and tag back to `origin`
- build the distributions
- publish to PyPI
- create the GitHub Release

This keeps PyPI publishing tied to `.github/workflows/release.yml`, which is the
workflow file that should be registered as the trusted publisher on PyPI.

## Cut a manual release

```bash
make release BUMP=patch
```

You can also set an explicit version:

```bash
make release VERSION=0.2.0
```

## What happens

- `scripts/release.py` updates `src/xpctl/__about__.py`
- the script runs `debaser` to derive the release name from the current Git SHA
- a release commit and annotated `v<version>` tag are created
- the current branch and tag are pushed when `origin` exists

The `Release v...` commit is ignored by the branch-triggered workflow, while the
tag push runs the same publishing job in `.github/workflows/release.yml`.

## CI release job

The release workflow:

- runs from `.github/workflows/release.yml`
- validates that the tag matches the package version
- builds `sdist` and `wheel`
- runs `twine check`
- publishes to PyPI
- creates a GitHub Release titled with the generated `debaser` name
