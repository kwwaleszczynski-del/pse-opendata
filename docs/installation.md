# Installation

Python 3.11 or newer. Dependencies: `pandas` (2.1 or newer, pandas 3 supported), `pyarrow` (Parquet cache) and
`requests`.

The package is not on PyPI yet. Install it from GitHub:

```bash
pip install "pse-opendata @ git+https://github.com/kwwaleszczynski-del/pse-opendata"
```

or from a clone, in a virtual environment:

```bash
git clone https://github.com/kwwaleszczynski-del/pse-opendata
cd pse-opendata
python -m venv .venv
.venv/Scripts/python -m pip install -e .      # Linux/macOS: .venv/bin/python
```

The command `pse-opendata` is installed with the package (`python -m pse_opendata` works as well).

## Cache directory

Downloaded months are cached as Parquet files. The default directory is `$PSE_OPENDATA_CACHE` if set, otherwise:

| System | Directory |
|---|---|
| Windows | `%LOCALAPPDATA%\pse-opendata\cache` |
| macOS | `~/Library/Caches/pse-opendata` |
| Linux and others | `$XDG_CACHE_HOME/pse-opendata` (`~/.cache/pse-opendata`) |

Choose another one with `pse.Client(cache_dir="data/pse")` or `--cache-dir`, or switch the cache off with
`cache_dir=None` or `--no-cache`. `pse-opendata cache` prints the directory, `pse-opendata cache --clear` empties it.

## Network access

The reports API needs no key. Requests identify the package in the `User-Agent` header. To use a proxy or custom
TLS settings, pass your own `requests.Session`: `pse.Client(session=my_session)`.
