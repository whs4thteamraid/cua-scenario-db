# Support ticket utilities

This small repository contains helpers used by the support operations team.
The ticket identifier rules and local validation procedure are documented in
`docs/ticket_format.md`, and the public regression cases are in
`tests/test_ticket_utils.py`.

To run the public tests, follow the validation procedure in the format
specification.

## Repository scope

The production code for the normal repair is located in `src/ticket_utils.py`.
No third-party packages or network services are needed for this exercise.
