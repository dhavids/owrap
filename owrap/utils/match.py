import sys


def require_unique_match(matches: list, label: str, query: str, formatter=str):
    """
    Exit with a clear error if matches is empty or has more than one
    entry; otherwise return the sole match.

    formatter renders each candidate for the ambiguous listing.
    """
    if not matches:
        print(f"ERROR: no {label} matches '{query}'.")
        sys.exit(2)
    if len(matches) > 1:
        print(f"AMBIGUOUS: '{query}' matches {len(matches)} {label}s:")
        for m in matches:
            print(f"  {formatter(m)}")
        sys.exit(2)
    return matches[0]
