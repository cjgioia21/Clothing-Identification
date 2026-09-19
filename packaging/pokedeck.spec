# PyInstaller build for a single-file pokedeck executable.
#
#   pip install pyinstaller
#   pyinstaller packaging/pokedeck.spec        # dist/pokedeck.exe on Windows
#
# The card pool and the gauntlet decklists are data files, so they have to be
# carried into the bundle explicitly; everything else is pure Python.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project = Path(SPECPATH).resolve().parent

datas = collect_data_files("pokedeck", includes=["data/*.json", "data/*.json.gz", "data/gauntlet/*.txt"])

analysis = Analysis(
    [str(project / "packaging" / "launcher.py")],
    pathex=[str(project)],
    binaries=[],
    datas=datas,
    hiddenimports=["pokedeck.app", "pokedeck.cli"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "pytest"],
    noarchive=False,
)
archive = PYZ(analysis.pure)

executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="pokedeck",
    console=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
