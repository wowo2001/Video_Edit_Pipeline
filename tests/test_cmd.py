import sys
import unittest

from core.cmd import run_cmd


class CommandTests(unittest.TestCase):
    def test_python_child_can_print_chinese_when_output_is_redirected(self):
        result = run_cmd([sys.executable, '-c', "print('中文路径')"], capture_output=True)
        self.assertEqual(result.stdout.strip(), '中文路径')

    def test_failure_reports_exit_code(self):
        with self.assertRaisesRegex(RuntimeError, '退出码 3'):
            run_cmd([sys.executable, '-c', 'raise SystemExit(3)'])


if __name__ == '__main__':
    unittest.main()
