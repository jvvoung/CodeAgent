import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.app_settings import get_int_setting, get_string_setting, load_settings, settings_path


class AppSettingsTest(unittest.TestCase):
    def test_reads_nested_json_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({
                "ollama": {"base_url": "http://127.0.0.1:11434", "num_ctx": 12_288},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"AURA_SETTINGS_FILE": str(path)}, clear=False):
                os.environ.pop("OLLAMA_BASE_URL", None)
                os.environ.pop("OLLAMA_NUM_CTX", None)
                self.assertEqual(settings_path(), path)
                self.assertEqual(load_settings()["ollama"]["num_ctx"], 12_288)
                self.assertEqual(get_int_setting("OLLAMA_NUM_CTX", 8_192, 4_096, 131_072), 12_288)
                self.assertEqual(
                    get_string_setting("OLLAMA_BASE_URL", "http://localhost:11434"),
                    "http://127.0.0.1:11434",
                )

    def test_environment_value_overrides_file_and_invalid_value_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({"ollama": {"num_ctx": 16_384}}), encoding="utf-8")
            with patch.dict(os.environ, {
                "AURA_SETTINGS_FILE": str(path),
                "OLLAMA_NUM_CTX": "8192",
            }, clear=False):
                self.assertEqual(get_int_setting("OLLAMA_NUM_CTX", 4_096, 4_096, 131_072), 8_192)
                os.environ["OLLAMA_NUM_CTX"] = "invalid"
                self.assertEqual(get_int_setting("OLLAMA_NUM_CTX", 4_096, 4_096, 131_072), 16_384)

    def test_explicit_missing_or_invalid_settings_file_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.json"
            with patch.dict(os.environ, {"AURA_SETTINGS_FILE": str(path)}, clear=False):
                with self.assertRaisesRegex(ValueError, "설정 파일을 찾을 수 없습니다"):
                    load_settings()
            path.write_text("{invalid", encoding="utf-8")
            with patch.dict(os.environ, {"AURA_SETTINGS_FILE": str(path)}, clear=False):
                with self.assertRaisesRegex(ValueError, "JSON 형식이 올바르지 않습니다"):
                    load_settings()


if __name__ == "__main__":
    unittest.main()
