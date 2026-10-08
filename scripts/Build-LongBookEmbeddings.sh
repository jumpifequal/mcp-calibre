#!/usr/bin/env bash
# ============================================================================
# Build-LongBookEmbeddings.sh
#
# Builds embeddings for very long books by raising the per-book chunk cap.
#
# Thin wrapper around "calibre_mcp.py --build-embeddings". The server caps the
# number of chunks per book (CALIBRE_MCP_EMBED_MAX_CHUNKS); very long volumes
# exceed it and get truncated, leaving the tail of the book unindexed. This
# script raises the cap, optionally limits ONNX threads, runs the build (in
# one call or in batches) and writes a JSON report.
#
# Run "./Build-LongBookEmbeddings.sh --help" for usage.
# Target platform: Linux (bash).
# ============================================================================
set -Eeuo pipefail

# --- Defaults ---------------------------------------------------------------
MAX_CHUNKS=8000
THREADS=0
BATCH_SIZE=0
PERSIST=0
PROFILE_FILE="${HOME:-}/.profile"
PY=""                                   # empty => auto-detect
ENTRY="calibre_mcp.py"
REPORT="embeddings-report.json"
SKIP_REPORT=0
BOOKS_ARG=""
BOOKS_FILE=""
IDS=""                                  # space-separated, deduplicated
COUNT=0
BAD=0

# --- Helpers ----------------------------------------------------------------
die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'

Build-LongBookEmbeddings.sh - build embeddings for very long books

USAGE
  ./Build-LongBookEmbeddings.sh [options]

  At least one of --books or --books-file is required.
  Options accept both "--opt value" and "--opt=value".

OPTIONS
  --books IDS         Book IDs separated by commas, e.g. 32,33,1047
                      May be repeated; combined with --books-file.
  --books-file FILE   Text file with IDs separated by commas, spaces,
                      semicolons or newlines. Everything after '#' on a line
                      is a comment, so IDs can be grouped by topic.
  --max-chunks N      Max chunks per book (CALIBRE_MCP_EMBED_MAX_CHUNKS).
                      Default 8000, range 1-1000000. Higher values index
                      longer books fully, at the cost of build time, memory
                      and index size.
  --threads N         ONNX threads (CALIBRE_MCP_EMBED_THREADS).
                      Default 0 = unset, server uses half the CPU cores.
                      Lower it to keep the machine responsive.
  --batch-size N      Split IDs into batches of N books, one build call each.
                      A failure reports the exact batch, so you can resume
                      with the remaining IDs. Default 0 = a single call.
  --persist           Persist --max-chunks beyond this run by writing an
                      "export CALIBRE_MCP_EMBED_MAX_CHUNKS=N" line to the
                      profile file (see --profile). The line is tagged, so
                      re-running updates it instead of duplicating it.
                      Takes effect in NEW login shells; the current shell is
                      not affected. Without it the value applies to this run
                      only.
  --profile FILE      Profile file used by --persist. Default: ~/.profile
                      (read by login shells). Use ~/.bashrc for interactive
                      non-login shells.
  --python PATH       Python interpreter. Default: auto-detect, in order:
                      .venv/bin/python, python3, python
  --entrypoint PATH   MCP server script. Default: calibre_mcp.py
  --report PATH       JSON embeddings report. Default: embeddings-report.json
                      (UTF-8)
  --skip-report       Do not generate the final report.
  -h, --help          Show this help.

EXAMPLES
  ./Build-LongBookEmbeddings.sh --books 32,33,1047
  ./Build-LongBookEmbeddings.sh --books 32,33,1047 --max-chunks 12000
  ./Build-LongBookEmbeddings.sh --books-file books.txt --batch-size 20 --threads 4 --persist

NOTES
  - Run from the project root (where .venv and calibre_mcp.py live), or pass
    --python and --entrypoint explicitly.
  - Under systemd services or cron, profile files are not read: set
    CALIBRE_MCP_EMBED_MAX_CHUNKS in the unit (Environment=) or crontab instead.
  - Duplicate IDs are removed; first-seen order is preserved.
  - Stops at the first failing step and returns that exit code.
    Argument and validation errors return 1.
  - Make it executable once with: chmod +x Build-LongBookEmbeddings.sh

EOF
}

# is_int VALUE - true if VALUE is a non-negative integer of at most 9 digits
# (the length cap avoids overflow in bash arithmetic).
is_int() { [[ $1 =~ ^[0-9]{1,9}$ ]]; }

# check_int VARNAME OPTION MIN MAX - validate an integer option range.
check_int() {
  local v=${!1}
  is_int "$v" && (( 10#$v >= $3 && 10#$v <= $4 )) \
    || die "$2 must be an integer between $3 and $4"
}

# add_tokens LIST - split IDs on commas, semicolons and whitespace; validate
# each one and append the new ones to IDS. Sets BAD=1 on invalid input.
add_tokens() {
  local raw=${1//[,;]/ } tok
  local -a toks=()
  read -ra toks <<<"$raw" || true
  for tok in ${toks[@]+"${toks[@]}"}; do
    if ! is_int "$tok"; then
      echo "ERROR: invalid book ID: $tok" >&2
      BAD=1
      continue
    fi
    tok=$((10#$tok))                    # normalise: 0012 -> 12
    case " $IDS " in
      *" $tok "*) ;;                    # already present
      *) IDS+=" $tok"; COUNT=$((COUNT + 1)) ;;
    esac
  done
}

# --- Parse arguments --------------------------------------------------------
# Normalise "--opt=value" into "--opt" "value".
args=()
for a in "$@"; do
  if [[ $a == --*=* ]]; then args+=("${a%%=*}" "${a#*=}"); else args+=("$a"); fi
done
set -- ${args[@]+"${args[@]}"}

while (( $# )); do
  case "$1" in
    -h|--help)     usage; exit 0 ;;
    --persist)     PERSIST=1; shift ;;
    --skip-report) SKIP_REPORT=1; shift ;;
    --books|--books-file|--max-chunks|--threads|--batch-size|--python|--entrypoint|--report|--profile)
      (( $# >= 2 )) && [[ -n $2 ]] || die "option $1 requires a value (see --help)"
      case "$1" in
        --books)       BOOKS_ARG+=" $2" ;;
        --books-file)  BOOKS_FILE=$2 ;;
        --max-chunks)  MAX_CHUNKS=$2 ;;
        --threads)     THREADS=$2 ;;
        --batch-size)  BATCH_SIZE=$2 ;;
        --python)      PY=$2 ;;
        --entrypoint)  ENTRY=$2 ;;
        --report)      REPORT=$2 ;;
        --profile)     PROFILE_FILE=$2 ;;
      esac
      shift 2 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# --- Validate numeric options -----------------------------------------------
check_int MAX_CHUNKS  --max-chunks 1 1000000
check_int THREADS     --threads    0 256
check_int BATCH_SIZE  --batch-size 0 100000
MAX_CHUNKS=$((10#$MAX_CHUNKS)); THREADS=$((10#$THREADS)); BATCH_SIZE=$((10#$BATCH_SIZE))

# --- Collect book IDs -------------------------------------------------------
# IDs may come from --books, from --books-file, or both.
[[ -n $BOOKS_ARG ]] && add_tokens "$BOOKS_ARG"

if [[ -n $BOOKS_FILE ]]; then
  [[ -f $BOOKS_FILE ]] || die "ID file not found: $BOOKS_FILE"
  # The "|| [[ -n $line ]]" clause also handles a last line with no newline.
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}                    # strip comments
    line=${line//$'\r'/}                # tolerate CRLF files
    add_tokens "$line"
  done <"$BOOKS_FILE"
fi

(( BAD == 0 )) || exit 1
(( COUNT > 0 )) || die "no book IDs provided. Use --books and/or --books-file (see --help)"

# --- Preflight checks -------------------------------------------------------
# Fail early with a clear message instead of a cryptic Python/launcher error.
if [[ -z $PY ]]; then
  for cand in .venv/bin/python python3 python; do
    if [[ -x $cand ]] || command -v "$cand" >/dev/null 2>&1; then PY=$cand; break; fi
  done
  [[ -n $PY ]] || die "no Python interpreter found (tried .venv/bin/python, python3, python)"
else
  [[ -x $PY ]] || command -v "$PY" >/dev/null 2>&1 || die "Python interpreter not found: $PY"
fi
[[ -f $ENTRY ]] || die "entrypoint not found: $ENTRY (run from the project root or pass --entrypoint)"

# --- Environment configuration ----------------------------------------------
# Session scope: exported to the Python child process only.
export CALIBRE_MCP_EMBED_MAX_CHUNKS=$MAX_CHUNKS

# Persistence (optional): write a tagged export line to the profile file.
# Idempotent: any previous line carrying our tag is replaced, other content
# is left untouched. "cat >" (not mv) keeps the file's mode and symlinks.
if (( PERSIST )); then
  [[ -n $PROFILE_FILE ]] || die "--persist needs a profile file: HOME is unset, pass --profile"
  TAG="# build-long-book-embeddings"
  tmp=$(mktemp)
  trap 'rm -f -- "$tmp"' EXIT
  if [[ -f $PROFILE_FILE ]]; then
    grep -vF -- "$TAG" "$PROFILE_FILE" >"$tmp" || true   # exit 1 = no lines left
  fi
  echo "export CALIBRE_MCP_EMBED_MAX_CHUNKS=$MAX_CHUNKS $TAG" >>"$tmp"
  cat -- "$tmp" >"$PROFILE_FILE" || die "cannot write $PROFILE_FILE"
  echo "MaxChunks persisted in $PROFILE_FILE (applies to new login shells)."
fi

# ONNX thread limit (optional). Unset => server default (half the cores).
THREADS_LABEL=default
if (( THREADS > 0 )); then
  export CALIBRE_MCP_EMBED_THREADS=$THREADS
  THREADS_LABEL=$THREADS
fi

# --- Batch sizing -----------------------------------------------------------
# BATCH_SIZE 0 means a single build call for all IDs.
if (( BATCH_SIZE == 0 )); then BATCH_SIZE=$COUNT; fi
BATCH_COUNT=$(( (COUNT + BATCH_SIZE - 1) / BATCH_SIZE ))
read -ra ALL <<<"$IDS"

echo "Books: $COUNT | MaxChunks: $MAX_CHUNKS | Threads: $THREADS_LABEL | Batches: $BATCH_COUNT"

# --- Build embeddings -------------------------------------------------------
SECONDS=0                               # bash builtin: seconds since assignment
n=0
for (( i = 0; i < COUNT; i += BATCH_SIZE )); do
  n=$((n + 1))
  batch=("${ALL[@]:i:BATCH_SIZE}")
  csv=$(IFS=,; echo "${batch[*]}")
  echo "[$n/$BATCH_COUNT] ${#batch[@]} books: $csv"

  # "&& rc=0 || rc=$?" captures the exit code without tripping "set -e".
  "$PY" "$ENTRY" --build-embeddings --books "$csv" && rc=0 || rc=$?
  if (( rc != 0 )); then
    echo "ERROR: build failed on batch $n/$BATCH_COUNT (exit code $rc)." >&2
    echo "Batch IDs: $csv" >&2
    exit "$rc"
  fi
done
printf 'Elapsed: %02d:%02d:%02d\n' $((SECONDS / 3600)) $((SECONDS % 3600 / 60)) $((SECONDS % 60))

# --- Embeddings report ------------------------------------------------------
if (( SKIP_REPORT )); then exit 0; fi

# Force UTF-8 on Python's stdout for this call only, so the redirected JSON is
# UTF-8 regardless of the locale.
PYTHONUTF8=1 "$PY" "$ENTRY" --embeddings-report --json >"$REPORT" && rc=0 || rc=$?
if (( rc != 0 )); then
  rm -f -- "$REPORT"                    # do not leave a partial report behind
  echo "ERROR: report generation failed (exit code $rc)." >&2
  exit "$rc"
fi
echo "Report: $(cd "$(dirname "$REPORT")" && pwd)/$(basename "$REPORT")"
