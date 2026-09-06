# Contributing

Contributions are welcome, especially Chinese emotion evaluation, source adapters, event clustering, and report quality.

1. Open an issue describing the problem or proposed behavior.
2. Create a branch and keep changes focused.
3. Add regression tests for aggregation, time boundaries, source validation, or report publishing changes.
4. Run `python -m unittest discover -s tests -v` with `PYTHONPATH=src`.
5. Open a pull request with the behavior change and verification results.

Use synthetic fixtures. Do not commit source credentials, usernames, or raw production comments. Keep demo and live outputs separate. Weekly/monthly aggregation must remain reproducible, including timezone, sampling, and deduplication rules.
