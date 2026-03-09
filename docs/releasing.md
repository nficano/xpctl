# Releases

`xpctl` uses a two-part release flow:

1. Local automation creates the version bump commit and annotated tag.
2. GitHub Actions publishes the distribution to PyPI and creates a GitHub Release.

## Requirements

- `debaser` installed locally
- push access to the target GitHub repository
- PyPI trusted publishing configured for the repository

## Cut a release

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

## CI release job

The release workflow:

- validates that the tag matches the package version
- builds `sdist` and `wheel`
- runs `twine check`
- publishes to PyPI
- creates a GitHub Release titled with the generated `debaser` name
