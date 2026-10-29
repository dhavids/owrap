import io
import threading
import time

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

    def test_idle_timeout_kills_before_the_hard_timeout(self):
        """
        A process that prints once then goes silent must be killed after
        idle_timeout, well before the much longer hard timeout.
        """
        t = Terminal(verbose=False, signals="none")
        start = time.monotonic()
        result = t.run(
            "python3 -c 'print(\"hi\", flush=True); import time; time.sleep(30)'",
            capture_output=True, print_output=True,
            timeout=120, idle_timeout=1,
        )
        elapsed = time.monotonic() - start
        assert result["returncode"] == -1
        assert result["idled_out"] is True
        assert result["timed_out"] is False
        assert "hi" in result["stdout"]
        assert elapsed < 10

    def test_new_output_resets_the_idle_clock(self):
        """
        A process that keeps producing output, slower than idle_timeout
        between lines, must not be killed early.
        """
        t = Terminal(verbose=False, signals="none")
        result = t.run(
            "python3 -c '"
            "import time\n"
            "for i in range(3):\n"
            "    print(i, flush=True)\n"
            "    time.sleep(0.3)\n"
            "'",
            capture_output=True, print_output=True,
            timeout=30, idle_timeout=2,
        )
        assert result["returncode"] == 0
        assert "0" in result["stdout"] and "2" in result["stdout"]

    def test_idle_timeout_after_marker_survives_a_longer_silent_stretch(self):
        """
        A silent stretch past the base idle_timeout, but under the
        extended one, must not be killed once the marker has printed.
        """
        t = Terminal(verbose=False, signals="none")
        result = t.run(
            "python3 -c 'print(\"saw marker\", flush=True); "
            "import time; time.sleep(1.5)'",
            capture_output=True, print_output=True,
            timeout=30, idle_timeout=1, idle_timeout_after=("marker", 5),
        )
        assert result["returncode"] == 0
        assert not result.get("idled_out")

    def test_idle_timeout_after_marker_still_kills_once_extended_budget_elapses(self):
        """
        Once the marker has printed, silence past the *extended* idle
        budget still kills the process.
        """
        t = Terminal(verbose=False, signals="none")
        result = t.run(
            "python3 -c 'print(\"saw marker\", flush=True); "
            "import time; time.sleep(30)'",
            capture_output=True, print_output=True,
            timeout=30, idle_timeout=1, idle_timeout_after=("marker", 1),
        )
        assert result["returncode"] == -1
        assert result["idled_out"] is True
