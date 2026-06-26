# Log Analyzer

This is a learning project, not a production log analysis tool.

Reads Apache/Nginx access logs in common or combined format and summarizes the
traffic. Counters can also be exported to CSV.

```bash
python3 log_analyzer.py example.log
python3 log_analyzer.py example.log --top 3 --csv report.csv
```

The parser expects access log lines like:

```text
127.0.0.1 - - [26/Jun/2026:12:00:00 +0200] "GET / HTTP/1.1" 200 1234 "-" "Mozilla/5.0"
```

It reports parsed and skipped lines, bytes served, status codes, methods, top
paths, top IPs, and top `4xx`/`5xx` paths. Unrecognized lines are included in
the total but not categorized.

Supported:

- Apache/Nginx access logs in common format
- Apache/Nginx access logs in combined format

Not supported:

- custom Nginx `log_format` output
- Apache/Nginx error logs
- JSON logs
- multiline logs and stack traces
- gzip-compressed logs

Topics demonstrated: regular expressions, file handling, `Counter`, CSV output,
type hints, and command-line arguments.
