"""Defaults work without initializing the application/database."""
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'backend/open_webui/utils/widget_defaults.py'
spec = importlib.util.spec_from_file_location('widget_defaults', path)
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)


class WidgetDefaultsTests(unittest.TestCase):
    def test_missing_and_blank_values_use_defaults(self):
        for value in (None, '', ' \n '):
            self.assertEqual(defaults.widget_system_prompt(value), defaults.DEFAULT_WIDGET_SYSTEM_PROMPT)
            self.assertEqual(defaults.widget_welcome_message(value), defaults.DEFAULT_WIDGET_WELCOME_MESSAGE)

    def test_custom_values_preserved(self):
        self.assertEqual(defaults.widget_system_prompt(' Custom instructions '), 'Custom instructions')
        self.assertEqual(defaults.widget_welcome_message(' Welcome! '), 'Welcome!')


if __name__ == '__main__':
    unittest.main()
