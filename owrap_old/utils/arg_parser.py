import argparse
import sys


def _print_scoped_help(sub, subcmd):
    print(f'\nHelp for "{subcmd}":', file=sys.stderr)
    positionals = sub._get_positional_actions()
    if positionals:
        print("\npositional arguments:", file=sys.stderr)
        for action in positionals:
            if action.choices:
                choices_str = "{" + ",".join(
                    str(c) for c in action.choices
                ) + "}"
                print(f"  {action.dest}: {choices_str}", file=sys.stderr)
            else:
                print(f"  {action.dest}", file=sys.stderr)
    optionals = [a for a in sub._actions if a.option_strings]
    if optionals:
        print("\noptions:", file=sys.stderr)
        for action in optionals:
            opts = ", ".join(action.option_strings)
            if action.nargs == 0:
                print(f"  {opts}", file=sys.stderr)
            else:
                print(f"  {opts} {action.dest.upper()}", file=sys.stderr)


class OwrapArgumentParser(argparse.ArgumentParser):
    """
    ArgumentParser that shows the failing subcommand's own help on error.
    """

    def error(self, message):
        subcmd = None
        sub = None
        if self._subparsers is not None:
            for action in self._subparsers._actions:
                choices = getattr(action, "choices", None)
                if choices:
                    for arg in sys.argv[1:]:
                        if arg in choices:
                            subcmd = arg
                            sub = choices[arg]
                            break
                if subcmd:
                    break
        if subcmd is None:
            self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        if "unrecognized arguments" in message and sub is not None:
            hint = self._reconstruct_hint(sub, subcmd)
            if hint:
                print(f"\nTip: {hint}.", file=sys.stderr)
        if subcmd and sub:
            _print_scoped_help(sub, subcmd)
        sys.exit(2)

    def _reconstruct_hint(self, sub, subcmd):
        flag_map = {}
        for action in sub._optionals._group_actions:
            for opt in action.option_strings:
                flag_map[opt] = action

        tokens = sys.argv[1:]
        if tokens and tokens[0] == subcmd:
            tokens = tokens[1:]
        positionals = []
        flags_and_values = []

        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.startswith('-') and token in flag_map:
                action = flag_map[token]
                nargs = action.nargs if action else None
                if nargs == 0:
                    flags_and_values.append((token,))
                    i += 1
                elif nargs is None:
                    if i + 1 < len(tokens):
                        flags_and_values.append((token, tokens[i + 1]))
                        i += 2
                    else:
                        flags_and_values.append((token,))
                        i += 1
                elif nargs in ('+', '*'):
                    vals = []
                    j = i + 1
                    while j < len(tokens) and not (
                        tokens[j].startswith('-') and tokens[j] in flag_map
                    ):
                        vals.append(tokens[j])
                        j += 1
                    flags_and_values.append((token, *vals))
                    i = j
                elif isinstance(nargs, int):
                    vals = []
                    for k in range(nargs):
                        if i + 1 + k < len(tokens):
                            vals.append(tokens[i + 1 + k])
                    flags_and_values.append((token, *vals))
                    i += 1 + len(vals)
                else:
                    if i + 1 < len(tokens):
                        flags_and_values.append((token, tokens[i + 1]))
                        i += 2
                    else:
                        flags_and_values.append((token,))
                        i += 1
            elif token.startswith('-'):
                flags_and_values.append((token,))
                i += 1
            else:
                positionals.append(token)
                i += 1

        pos_str = ' '.join(positionals)
        flag_str = ' '.join(t for fv in flags_and_values for t in fv)
        if pos_str and flag_str:
            return f"put '{pos_str}' before '{flag_str.split()[0]}'"
        return None
