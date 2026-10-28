# Proposals

A proposal is a change you want in owrap's own tooling. Do not work around an owrap problem in your project. File a proposal instead.


## Filing

1. Run `owrap get proposal` to see the open proposals.
2. If one matches, add detail to it with `owrap do proposal <id> note "<text>"`.
3. Otherwise run `owrap get proposal template`, fill it in, save it to a file, and run `owrap add proposal <file>`.

`owrap add proposal` refuses a file that is missing a required section or that closely matches an open proposal. Pass `--force` only if the match is a different problem.


## Working

Only the session whose project is `owrap` may work proposals. At the start of a session, run `owrap get proposal` and take the open ones with `owrap do proposal <id> claim`. When the change is made, run `owrap do proposal <id> done "<what changed>"`. Run `owrap do proposal <id> reject "<reason>"` for one that will not be done.

Other sessions may read proposals and add notes, but a `claim`, `done`, or `reject` from them is refused.


## Not proposals

Options you offer your user inside your own project are suggestions, not proposals. List them in your reply and wait for the user to choose.
