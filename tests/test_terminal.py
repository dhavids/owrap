import io

from owrap.utils.terminal import Terminal


class TestTerminalRunStandard:
    def test_tee_cleaned_of_ansi_and_crlf(self):
        t = Terminal(verbose=False, signals="none")
        tee_file = io.StringIO()
        result = t.run(
            """python3 -c 'import sys; sys.stdout.write(chr(27) + "[0mhello\\r\\n")'""",
            capture_output=True,
            print_output=True,
            silent=False,
            tee_file=tee_file,
        )
        tee_content = tee_file.getvalue()
        assert "\x1b" not in tee_content
        assert "\r\n" not in tee_content
        assert "hello\n" in tee_content
        assert "\x1b[0mhello" in result["stdout"]
        assert result["returncode"] == 0
