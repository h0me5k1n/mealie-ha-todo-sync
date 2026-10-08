## Summary

<!-- Describe what this PR does -->

## Version bump

The release is determined automatically from commit messages using [Conventional Commits](https://www.conventionalcommits.org/) (highest match wins). When squash-merging, the PR title is the commit message.

| Commit message | Bump |
|---|---|
| `feat!: ...`, `fix!: ...`, or a `BREAKING CHANGE:` footer | major |
| `feat: ...` | minor |
| `fix: ...` | patch |
| *(none of the above)* | patch (default) |

## Checklist

- [ ] `CHANGELOG.md` updated with an entry for the upcoming version
- [ ] Tests pass locally (`pytest tests/`)
