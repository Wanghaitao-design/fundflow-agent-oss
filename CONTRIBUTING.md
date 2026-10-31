# Contributing

Thanks for your interest in Fundflow Agent.

## Scope

Bug reports, documentation fixes, tooling improvements, and new synthetic scenarios are welcome. This project is a research prototype; changes that affect investigative conclusions need an explicit evidence trail.

## Before you open a pull request

1. Install the Python environment and run the checks:

   ```powershell
   py -3.12 run.py setup --python-only
   py -3.12 run.py verify
   ```

2. Keep the change focused and describe the problem it solves.
3. Update both `README.md` and `README.zh-CN.md` for user-visible documentation changes.
4. Do not modify `vendor/agnes-harness/`. It is an unmodified upstream snapshot; put changes in `agent/`, `run.py`, or `docs/`.
5. Add or update a synthetic scenario when changing detection or acceptance behavior.

## Data and credentials

- Use synthetic data only.
- Never commit real statements, identity tables, case artifacts, credentials, or session databases.
- Never paste credentials or real case data into an issue, pull request, or attachment.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0.
