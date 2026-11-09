#!/bin/zsh
# Daily refresh at 07:00 (launchd: ca.canadabasketball.wnt-player-watch)
#  1. build          -> site/index.html  (local copy)
#  2. public build   -> docs/index.html  (same content) -> pushed to GitHub Pages
cd "$(dirname "$0")"
LOG="logs/$(date +%F).log"
mkdir -p logs
{
  echo "=== $(date) ==="
  cp site/index.html site/index.prev.html 2>/dev/null
  if .venv/bin/python build.py; then echo "private build OK"
  else echo "PRIVATE BUILD FAILED - keeping yesterday's page"; cp site/index.prev.html site/index.html 2>/dev/null; fi

  if .venv/bin/python build.py --offline --public; then
    echo "public build OK"
    if ! git diff --quiet -- docs/index.html; then
      git add docs/index.html
      git commit -q -m "Daily data refresh $(date +%F)" && git push -q origin main && echo "pushed to GitHub Pages"
    else
      echo "public page unchanged"
    fi
  else
    echo "PUBLIC BUILD FAILED - site not updated"
  fi
} >> "$LOG" 2>&1
grep -q "FAILED" "$LOG" && echo "WARNING: something failed today, see $LOG" >> "$LOG"
exit 0
