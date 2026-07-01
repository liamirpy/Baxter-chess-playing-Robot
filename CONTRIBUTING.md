# Contributing

Contributions are welcome. Please keep robot-safety changes easy to review.

Before opening a pull request:

```bash
python3 -m py_compile $(find controller ros scripts -name '*.py')
```

For motion changes, document what was tested physically and whether the test was done with `--dry-run`, `test_square.py`, or real pick/place movement.
