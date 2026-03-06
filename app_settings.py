"""Persistent settings for GLCD Font Creator."""
import json
from pathlib import Path


class AppSettings:
    _settings_path = Path.home() / '.glcd_font_creator.json'

    def __init__(self):
        self._data = self._load()

    def _load(self):
        if self._settings_path.exists():
            try:
                with open(self._settings_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self):
        try:
            with open(self._settings_path, 'w') as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass

    @property
    def font_dir(self):
        return self._data.get('font_dir', str(Path.home()))

    @font_dir.setter
    def font_dir(self, v):
        self._data['font_dir'] = str(v)

    @property
    def save_dir(self):
        return self._data.get('save_dir', str(Path.home()))

    @save_dir.setter
    def save_dir(self, v):
        self._data['save_dir'] = str(v)
