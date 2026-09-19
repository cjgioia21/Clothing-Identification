"""The double-click front end."""

import builtins

import pytest

from pokedeck import app
from pokedeck.__main__ import main as entry_main


def feed(monkeypatch, answers):
    replies = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(replies))


def test_the_menu_loads_a_deck_and_checks_it(monkeypatch, capsys, tmp_path):
    deck = tmp_path / "deck.txt"
    deck.write_text(open("examples/dragapult.txt", encoding="utf-8").read(), encoding="utf-8")
    feed(monkeypatch, [str(deck), "1", "7"])
    assert app.main([]) == 0
    out = capsys.readouterr().out
    assert "Loaded deck.txt" in out
    assert "Format (standard)" in out


def test_a_deck_passed_on_the_command_line_skips_the_prompt(monkeypatch, capsys):
    feed(monkeypatch, ["7"])
    assert app.main(["examples/dragapult.txt"]) == 0
    assert "Loaded dragapult.txt" in capsys.readouterr().out


def test_an_unreadable_file_asks_again(monkeypatch, capsys):
    feed(monkeypatch, ["", ""])
    assert app.main(["not-a-deck.txt"]) == 0
    assert "Could not read that decklist" in capsys.readouterr().out


def test_quitting_from_the_prompt_exits(monkeypatch):
    feed(monkeypatch, [""])
    assert app.main([]) == 0


def test_the_entry_point_routes_commands_to_the_cli(capsys):
    assert entry_main(["check", "examples/dragapult.txt"]) == 0
    assert "60 cards" in capsys.readouterr().out


def test_the_entry_point_routes_a_bare_path_to_the_menu(monkeypatch, capsys):
    feed(monkeypatch, ["7"])
    assert entry_main(["examples/dragapult.txt"]) == 0
    assert "Loaded dragapult.txt" in capsys.readouterr().out
