from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def test_modules_import_independently(self):
        modules = ['src.agent', 'src.tools', 'src.tasks_variants', 'src.holdout_tasks',
                   'src.tasks', 'src.task_types', 'src.configs', 'src.ticket_system',
                   'src.llm', 'src.raw_llm', 'experiments', 'run', 'export_materials', 'analyze']
        for name in modules:
            with self.subTest(module=name):
                result = subprocess.run(
                    [sys.executable, '-B', '-c', f'import importlib; importlib.import_module({name!r})'],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_package_does_not_inject_src_into_search_path(self):
        code = (
            'import sys, types; from pathlib import Path; '
            'sys.modules["agent"] = types.ModuleType("agent"); '
            'sys.modules["tools"] = types.ModuleType("tools"); '
            'from src.agent import Agent; '
            'from src.tools import check_value, to_ollama, ALL_SPECS; '
            'import experiments, run, export_materials; '
            'assert Agent.__module__ == "src.agent"; '
            'assert Path.cwd() / "src" not in [Path(p).resolve() for p in sys.path]'
        )
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_entry_points_from_other_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            commands = [
                [sys.executable, '-B', str(ROOT / 'run.py'), '--series', 'holdout',
                 '--tasks', 'H05', '--configs', 'base', '--plan'],
                [sys.executable, '-B', str(ROOT / 'analyze.py'), '--out', str(Path(temp) / 'analysis')],
            ]
            for command in commands:
                with self.subTest(script=command[2]):
                    result = subprocess.run(command, cwd=temp, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(temp) / 'analysis' / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
