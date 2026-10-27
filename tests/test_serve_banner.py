"""`inklight serve` says which library it opens: the library lives in the Inklight home, shared by installations."""

from typer.testing import CliRunner

from inklight.cli import app as cli_app


def test_serve_names_the_library_it_opens(tmp_path, monkeypatch):
    home = tmp_path / "fresh-home"
    monkeypatch.setenv("INKLIGHT_HOME", str(home))
    started = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: started.update(kw))
    result = CliRunner().invoke(cli_app, ["serve", "--no-open", "--port", "8799"])
    assert result.exit_code == 0, result.output
    assert "library" in result.output and "INKLIGHT_HOME" in result.output
    assert str(home) in result.output.replace("\n", "")
    assert started["port"] == 8799 and started["host"] == "127.0.0.1"
