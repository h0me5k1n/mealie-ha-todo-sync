## Summary

<!-- Describe what this PR does -->

## Version bump

Include one of the following tokens in your commit message or PR title to control the release version on merge to main:

- `[PATCH]` — bug fixes, documentation, minor tweaks (default if omitted)
- `[MINOR]` — new backwards-compatible feature
- `[MAJOR]` — breaking change

## Checklist

- [ ] `CHANGELOG.md` updated with an entry for the upcoming version
- [ ] Version bump token included in commit message or PR title (see above)
- [ ] Tests pass locally (`pytest tests/`)
