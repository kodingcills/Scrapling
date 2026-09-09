# lead_engine scripts

## Scheduled `targets` runs (cron)

`run_targets.sh` is the cron entry point for the weekly lead-generation
run. It cds into `lead_engine/`, runs
`python main.py targets data/target_companies.yaml` through `uv` (using an
absolute `uv` path because cron's PATH is minimal), and appends everything
to `logs/targets_YYYYMMDD.log` so there is a paper trail beyond the
run-summary email.

### Crontab line

```
0 21 * * 0 /Users/tofuinparis/Projects/Scrapling/lead_engine/scripts/run_targets.sh
```

That is: 21:00 local time every Sunday. The weekly cadence is a **default,
not a hard requirement** - it was chosen because Findymail credits are
finite and a scheduled run must never be able to spend the whole remaining
balance in one go (the `--max-enrich` flag in `main.py targets` hard-caps
enrichment per run at 10 leads by default). Once the real credit balance
and burn rate are known, tune the schedule with `crontab -e`.

Install/verify with:

```bash
crontab -l                                # check current entries
crontab -e                                # add the line above
```

### macOS gotcha: Full Disk Access for cron

On modern macOS, cron jobs **silently fail** to access files in your home
directory unless the cron binary itself has Full Disk Access. If a
scheduled run produces no log file in `logs/` and no email, this
permission is the first thing to check, not a code bug:

1. System Settings > Privacy & Security > Full Disk Access
2. Click `+`, press `Cmd+Shift+G`, enter `/usr/sbin/cron`, add it, toggle
   it on.

`run_targets.sh` is safe to run manually at any time; it is the exact same
invocation cron performs.
