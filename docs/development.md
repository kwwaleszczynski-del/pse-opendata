# Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,docs]"     # Linux/macOS: .venv/bin/python
pytest -q                     # offline tests on recorded responses
ruff check .
mypy                          # type check of src/
mkdocs build --strict         # documentation into site/
```

## Tests

The default test suite never touches the network: it replays real PSE responses recorded in
`tests/fixtures` (DST days, paging, partial days, offers with repeated rows, legacy files with old and new
layouts, the seam of June 2024) and synthetic records for cache tests. Tests compare time stamps by value, so they
pass with pandas 2 and pandas 3.

Live tests call the real servers and are skipped unless asked for:

```bash
pytest -q --live tests/live
```

They check that the catalogue matches the OpenAPI description of the reports API, that RCE and the legacy export
answer as expected and that offers are complete.

To record the fixtures again:

```bash
python scripts/record_fixtures.py
```

After changing the catalogue, regenerate the catalogue page (a test checks it):

```bash
python scripts/gen_docs.py
```

## Continuous integration

`.github/workflows/ci.yml` runs ruff, mypy and the offline tests on Python 3.11, 3.12 and 3.13 (plus the oldest
supported pandas 2.1, pyarrow 14 and requests 2.31), builds the wheel and
the documentation. `.github/workflows/docs.yml` publishes the documentation to GitHub Pages from `main`.

## Releasing

`.github/workflows/release.yml` builds the sdist and wheel on every published GitHub release and uploads them to
PyPI with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no API token). Publishing is switched off
until the repository variable `PYPI_PUBLISH` is set to `true`. To enable it:

1. On PyPI, add a pending trusted publisher for project `pse-opendata`: owner `kwwaleszczynski-del`, repository
   `pse-opendata`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository, create the environment `pypi` and set the variable `PYPI_PUBLISH=true`.
3. Update the version in `src/pse_opendata/_version.py` and `CHANGELOG.md`, tag `vX.Y.Z` and publish a release.
