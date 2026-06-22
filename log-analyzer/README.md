# Log Analyzer

Reads a text log, counts recognized log levels and dates, and lists the most
frequent error messages. Error counts can also be exported to CSV.

```bash
python3 log_analyzer.py example.log
python3 log_analyzer.py example.log --top 3 --csv errors.csv
```

The parser expects an optional `YYYY-MM-DD` date followed somewhere by one of
`DEBUG`, `INFO`, `WARNING`, `WARN`, `ERROR`, or `CRITICAL`. Unrecognized lines
are included in the total but not categorized.

Topics demonstrated: regular expressions, file handling, `Counter`, CSV output,
type hints, and command-line arguments.
