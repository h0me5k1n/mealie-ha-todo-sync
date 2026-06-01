## Summary

<!-- Describe what this PR does -->

## Version bump

The release is determined automatically from commit messages using these rules (highest match wins):

| Commit prefix / token | Bump |
|---|---|
| `feat:` or `#minor` anywhere in message | minor |
| `fix:` or `#patch` anywhere in message | patch |
| `BREAKING CHANGE` or `#major` anywhere in message | major |
| *(none of the above)* | patch (default) |

## Checklist

- [ ] `CHANGELOG.md` updated with an entry for the upcoming version
- [ ] Tests pass locally (`pytest tests/`)
