import io
import threading

from owrap.utils.dispatch.terminal import Terminal


class TestSignalHandlersOffMainThread:
    def test_register_signal_handlers_skips_silently_off_main_thread(self):
        """
        Python only allows installing signal handlers from the main
        thread — a background-thread dispatch (e.g. the daemon's
        check_all_attached) must not crash trying to register them.
        """
        t = Terminal(verbose=False)
        error = {}

        def _register():
            try:
                t.register_signal_handlers()
            except ValueError as e:
                error["e"] = e

        thread = threading.Thread(target=_register)
        thread.start()
        thread.join()

        assert "e" not in error
        assert not t._signal_handlers_registered

    def test_run_off_main_thread_does_not_crash(self):
        result = {}

        def _run():
            t = Terminal(verbose=False)
            result["r"] = t.run("echo hi", capture_output=True, print_output=False)

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join()

        assert result["r"]["returncode"] == 0


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
