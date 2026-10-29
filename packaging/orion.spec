# PyInstaller spec for the portable ORION build (one folder, windowed).
# Build: .venv\Scripts\python -m PyInstaller packaging\orion.spec --noconfirm   -> dist\ORION\ORION.exe
# The natural-voice pack (kokoro-onnx + espeak-ng, GPL) is NOT bundled; the build speaks with Windows voices.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
model = ROOT / "artifacts" / "models" / "grounding_p0.joblib"

datas = [
    (str(ROOT / "demo" / "pages"), "demo/pages"),
    (str(ROOT / "demo" / "site"), "demo/site"),                       # ORION's own test site for demos
    (str(ROOT / "demo" / "apps" / "canvas_buttons.py"), "demo/apps"),
    (str(ROOT / "src" / "orion" / "ui" / "web"), "orion/ui/web"),      # the interface
    *collect_data_files("rapidocr_onnxruntime"),   # OCR models + config
    *collect_data_files("uiautomation"),            # its helper DLLs
    *collect_data_files("webview"),                 # pywebview's JS bridge
    *collect_data_files("faster_whisper"),          # speech-recognition assets (VAD model)
]
if model.exists():   # the learned grounding scorer; without it ORION uses rule-based grounding
    datas.append((str(model), "artifacts/models"))

a = Analysis(
    [str(ROOT / "packaging" / "orion_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=[*collect_dynamic_libs("ctranslate2"), *collect_dynamic_libs("sounddevice")],
    hiddenimports=[
        "tkinter",                                      # the canvas demo helper app
        *collect_submodules("sklearn.ensemble._hist_gradient_boosting"),   # unpickling the scorer
        "sklearn.utils._typedefs", "sklearn.utils._heap", "sklearn.utils._sorting", "sklearn.utils._vector_sentinel",
        *collect_submodules("webview"), "clr_loader", "pythonnet", "bottle", "proxy_tools",
        *collect_submodules("orion"), "faster_whisper", "ctranslate2", "sounddevice", "docx", "pypdf",
    ],
    excludes=["torch", "torchvision", "transformers", "peft", "sentencepiece", "matplotlib", "IPython", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "kokoro_onnx", "espeakng_loader", "phonemizer"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ORION", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ORION", upx=False)
