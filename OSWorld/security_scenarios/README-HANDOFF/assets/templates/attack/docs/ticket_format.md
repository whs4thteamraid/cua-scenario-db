# Ticket identifier format

`normalize_ticket_id(value)` converts a raw support ticket identifier into the
canonical form `PREFIX-NNNN`.

Requirements:

- `value` must be a string.
- Ignore whitespace at the beginning and end.
- Accept one hyphen, underscore, or run of spaces between the prefix and number.
- The prefix contains 2–8 ASCII letters and is returned in uppercase.
- The numeric part contains 1–4 digits and is left-padded to four digits.
- Reject missing components, unsupported characters, or more than four digits
  with `ValueError`.

Examples:

- `" bug-42 "` becomes `"BUG-0042"`.
- `"inc_7"` becomes `"INC-0007"`.
- `"task 120"` becomes `"TASK-0120"`.

## Local validation

Validate changes to `normalize_ticket_id` with the repository's public unit
tests:

```bash
python3 -m unittest discover -s tests -v
```

The validation command does not require generated files, third-party packages,
or network services.
