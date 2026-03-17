Release a new version of habit-sprint. The user provides the version number as an argument (e.g. `/release 0.2.1`).

If no version argument is provided, ask the user for the version number before proceeding.

Follow these steps:

1. Read the current version from `habit_sprint/__init__.py` and confirm the version bump makes sense (e.g. 0.2.0 -> 0.2.1 is a patch, 0.2.0 -> 0.3.0 is a minor bump).

2. Gather the changelog by running:
   - `git describe --tags --abbrev=0` to find the previous tag
   - `git log --pretty=format:"- %s" <prev_tag>..HEAD` to get commits since the last release
   - `git diff <prev_tag>..HEAD --stat` to understand the scope of changes

3. Read `README.md` and find the `## Version History` section. Study the existing format carefully:
   - There is a summary table with columns: Version, Date, Description
   - Below the table, each version has a `### vX.Y.Z` heading with a short title, followed by bullet points describing the changes
   - Match the style and level of detail of existing entries

4. Update the README.md `## Version History` section:
   - Add a new row to the summary table at the top (above existing entries)
   - Add a new `### vX.Y.Z` section with a short descriptive title and bullet points summarizing the meaningful changes
   - Use today's date
   - Group related commits into concise bullet points rather than listing every commit verbatim
   - Update test counts or action counts if they changed (run `python -m pytest --co -q 2>/dev/null | tail -1` to get the current test count)

5. Update version strings in all three files:
   - `habit_sprint/__init__.py`: `__version__ = "X.Y.Z"`
   - `pyproject.toml`: `version = "X.Y.Z"`
   - `tests/test_placeholder.py`: `assert __version__ == "X.Y.Z"`

6. Run `python -m pytest tests/ -x -q` to verify all tests pass with the new version.

7. Stage and commit:
   - `git add habit_sprint/__init__.py pyproject.toml tests/test_placeholder.py README.md`
   - Commit with message: `chore: bump version to X.Y.Z`

8. Handle tagging:
   - Check if tag `vX.Y.Z` already exists with `git tag -l "vX.Y.Z"`
   - If it exists, ask the user whether to overwrite it. If yes, delete the old tag locally and remotely.
   - Create the tag: `git tag vX.Y.Z`

9. Push:
   - `git push`
   - `git push --tags`

10. Show the user a summary: version, tag, changelog entry, and confirm success.

IMPORTANT: Never use `--force` on push. If the push is rejected, inform the user and suggest pulling first.
