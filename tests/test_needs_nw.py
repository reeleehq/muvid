"""muvid#368: a module needing nw says which extra provides it when nw is absent."""

import subprocess
import sys
import textwrap

import pytest

_MODULES = [
    "muvid.genre",
    "muvid.genre_music_video",
    "muvid.downloads",
    "muvid.genre_lyric_video",
    "muvid.genre_subgenres",
    "muvid.catalog",
]


@pytest.mark.parametrize("module", _MODULES)
def test_missing_nw_names_the_extra(module):
    code = textwrap.dedent(
        f"""
        import sys
        sys.modules["nw"] = None  # makes `import nw` fail like an absent package
        import importlib.util
        _find = importlib.util.find_spec
        importlib.util.find_spec = lambda n, *a, **k: None if n == "nw" else _find(n, *a, **k)
        try:
            import {module}
        except ImportError as e:
            print(e)
        else:
            raise SystemExit("imported without nw")
        """
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert "muvid[mcp]" in out.stdout and module in out.stdout
