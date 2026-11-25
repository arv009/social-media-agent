"""Old entry point, kept so existing deploy settings still work. The app now lives in streamlit_app.py.

    streamlit run app/streamlit_app.py
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("streamlit_app.py")), run_name="__main__")
