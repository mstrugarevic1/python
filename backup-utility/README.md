# Backup Utility

Creates and restores named, timestamped `tar.gz` backups while preserving file
permissions, ownership IDs, timestamps, symbolic links, hard links, ACLs, and
extended attributes supported by the installed `tar`.

```bash
# Save a named backup set.
python3 backup.py set web /srv/web /var/backups/web \
  --exclude '*.log' --exclude '.git'

# Inspect sets, preview, then back up.
python3 backup.py list
python3 backup.py list web
python3 backup.py backup web --dry-run
sudo python3 backup.py backup web

# Restore into a new or empty directory.
sudo python3 backup.py restore /var/backups/web/web-20260623-143000-123456.tar.gz /srv/restore-test
```

Set definitions live in `~/.config/backup-utility/sets.json`. Set
`BACKUP_UTILITY_CONFIG` to use another path, which is useful for a service
account.

Normal output contains only start, completion, size, duration, and errors. Use
`--verbose` on `backup` or `restore` for per-file tar output. A failed backup is
retained with a `.incomplete` suffix and is never presented as complete.

GNU tar receives explicit ACL, xattr, SELinux, sparse-file, numeric-owner, and
restore flags. BSD tar uses its native pax metadata support and `-p` restore.
Run as root when ownership and system metadata must be captured or restored.

This is not a consistent snapshot of live application data. Use database-native
dumps or filesystem snapshots when files must represent one point in time.
