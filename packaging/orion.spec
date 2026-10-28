# PyInstaller spec for the portable ORION build (one folder, windowed).
# Build: .venv\Scripts\python -m PyInstaller packaging\orion.spec --noconfirm   -> dist\ORION\ORION.exe
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
model = ROOT / "artifacts" / "models" / "grounding_p0.joblib"

datas = [
    (str(ROOT / "demo" / "pages"), "demo/pages"),
    (str(ROOT / "demo" / "apps" / "canvas_buttons.py"), "demo/apps"),
    *collect_data_files("rapidocr_onnxruntime"),   # OCR models + config
    *collect_data_files("uiautomation"),            # its helper DLLs
]
if model.exists():   # the learned grounding scorer; without it ORION uses rule-based grounding
    datas.append((str(model), "artifacts/models"))

a = Analysis(
    [str(ROOT / "packaging" / "orion_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=[
        "tkinter",                                      # the canvas demo helper app
        *collect_submodules("sklearn.ensemble._hist_gradient_boosting"),   # unpickling the scorer
        "sklearn.utils._typedefs", "sklearn.utils._heap", "sklearn.utils._sorting", "sklearn.utils._vector_sentinel",
    ],
    excludes=["torch", "torchvision", "transformers", "peft", "sentencepiece", "matplotlib", "IPython", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ORION", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ORION", upx=False)
