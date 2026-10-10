"""
`dispatch()`'s `--flag`/`--flag value` splitting -- closes the gap
where a kind's own documented `--note`/`--error`/`--ctx` flags never
actually reached the method through `cli.py`, which only ever passed
pure positionals. Matched by name against the resolved method's own
signature, so positional-only calls (everything before this) must
keep behaving identically. Also covers `SHORT_FLAGS` (`-i`/`-t`/`-m`/
...), the dispatch-kind short aliases the old `oread`/`orun`/`oagent`/
`oexec` shims supported.
"""
import pytest

from owrap.actions import Actions, dispatch


class _Toy(Actions):
    kind = "toy"
    messages = {"done": "{text}", "add": "{text}", "start": "{text}"}

    def done(self, error: str = None) -> None:
        self._ok("done", text=f"error={error!r}")

    def add(self, *paths, note: str = None) -> None:
        self._ok("add", text=f"paths={paths!r} note={note!r}")

    def start(self, subproject: str = None, ctx: bool = False) -> None:
        self._ok("start", text=f"subproject={subproject!r} ctx={ctx!r}")


class _ToyDispatch(Actions):
    kind = "toydispatch"
    messages = {"start": "{text}"}

    def start(
        self, data: str = None, id: str = None, timeout: int = None,
        model: str = None, grep: str = None, summarise: bool = False,
        details: str = None, verbose: bool = False, prompt_style: str = None,
    ) -> None:
        self._ok(
            "start",
            text=(
                f"data={data!r} id={id!r} timeout={timeout!r} model={model!r} "
                f"grep={grep!r} summarise={summarise!r} details={details!r} "
                f"verbose={verbose!r} prompt_style={prompt_style!r}"
            ),
        )


@pytest.fixture
def registry():
    return {"toy": _Toy, "toydispatch": _ToyDispatch}


def test_value_flag_reaches_the_method_as_a_keyword(registry, capsys):
    dispatch(registry, "toy", "done", "--error", "opencode down")
    assert "error='opencode down'" in capsys.readouterr().out


def test_bool_flag_present_sets_true(registry, capsys):
    dispatch(registry, "toy", "start", "--ctx")
    assert "ctx=True" in capsys.readouterr().out


def test_bool_flag_absent_keeps_default(registry, capsys):
    dispatch(registry, "toy", "start", "docs")
    out = capsys.readouterr().out
    assert "subproject='docs'" in out
    assert "ctx=False" in out


def test_flag_mixed_with_var_positional_args(registry, capsys):
    dispatch(registry, "toy", "add", "file1", "file2", "--note", "msg")
    out = capsys.readouterr().out
    assert "paths=('file1', 'file2')" in out
    assert "note='msg'" in out


def test_pure_positional_call_is_unaffected(registry, capsys):
    """
    No `--` token anywhere -- padding/positional behavior must be
    identical to before flag-splitting existed.
    """
    dispatch(registry, "toy", "done", "some text, not a flag")
    assert "error='some text, not a flag'" in capsys.readouterr().out


# SHORT_FLAGS -- the old oread/orun/oagent/oexec shims' -i/-t/-m/...

def test_every_short_flag_resolves_to_its_long_counterpart(registry, capsys):
    dispatch(
        registry, "toydispatch", "start", "the data",
        "-i", "r1", "-t", "55", "-m", "opus", "-g", "pattern",
        "-s", "-d", "focus", "-v", "-p", "terse",
    )
    out = capsys.readouterr().out
    assert "data='the data'" in out
    assert "id='r1'" in out
    assert "timeout='55'" in out
    assert "model='opus'" in out
    assert "grep='pattern'" in out
    assert "summarise=True" in out
    assert "details='focus'" in out
    assert "verbose=True" in out
    assert "prompt_style='terse'" in out


def test_short_flag_falls_through_as_positional_when_param_is_absent(
    registry, capsys,
):
    """
    `-i`/`-t`/etc. only fire for a method that actually declares that
    parameter -- `toy.done` has no `id`, so `-i` lands as plain text.
    """
    dispatch(registry, "toy", "done", "-i")
    assert "error='-i'" in capsys.readouterr().out


# A flagged parameter can sit in the middle of a signature, not just
# trail it (`Session.start`'s `project` is between `project_name` and
# `repository`) -- positional padding must bind every remaining slot
# by name, not splice *args and let position drift.

class _ToyMiddleFlag(Actions):
    kind = "toymiddle"
    messages = {"start": "{text}"}

    def start(self, first: str = None, middle: str = None, last: str = None) -> None:
        self._ok("start", text=f"first={first!r} middle={middle!r} last={last!r}")


def test_flag_for_a_middle_parameter_does_not_shift_later_positionals(capsys):
    dispatch({"toymiddle": _ToyMiddleFlag}, "toymiddle", "start", "--middle", "m")
    out = capsys.readouterr().out
    assert "first=None" in out
    assert "middle='m'" in out
    assert "last=None" in out


def test_flag_for_a_middle_parameter_leaves_other_positionals_in_place(capsys):
    dispatch(
        {"toymiddle": _ToyMiddleFlag}, "toymiddle", "start", "f", "--middle", "m",
    )
    out = capsys.readouterr().out
    assert "first='f'" in out
    assert "middle='m'" in out
    assert "last=None" in out
