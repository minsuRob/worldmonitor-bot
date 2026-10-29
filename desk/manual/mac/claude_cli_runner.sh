#!/bin/bash
# Claude CLI batch path — step 3 (Mac): run exported LLM jobs through `claude -p`.
#
# Canonical copy: worldmonitor-bot desk/manual/mac/claude_cli_runner.sh (tracked; see desk/manual/ROUTINE.md)
# Older untracked copies (worldmonitor tools/claude-cli/, worldmonitor-bot tools/) can go once the routine calls this path.
#
# Usage: claude_cli_runner.sh <jobs.jsonl> [results.jsonl]
#   env CLAUDE_CLI_MAX_JOBS   max jobs per run (default 20)
#   env CLAUDE_CLI_MODEL      optional --model (default: the CLI's own default)
#   env CLAUDE_CLI_EFFORT     optional --effort (e.g. low|medium|high)
#   Both are recorded as requestedModel / requestedEffort (null = not set) in every result line and in the
#   meta file; claudeModel is the model the CLI itself reported.
#   env CLAUDE_CLI_TIMEOUT    per-job timeout seconds (default 300)
#
# Cost safety:
#   * ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are unset, so the CLI can only use
#     the logged-in Claude subscription (never pay-per-use API billing).
#   * ANTHROPIC_BASE_URL is kept only if its host is anthropic.com; otherwise unset.
#   * Bedrock/Vertex/Foundry switches are unset.
#   * No MCP servers (--strict-mcp-config with an empty config), no tools,
#     --safe-mode when supported. No Claude config or MCP settings are modified.
#   * Each job's init event records apiKeySource; "none" = subscription login.
set -euo pipefail

JOBS="${1:?usage: claude_cli_runner.sh <jobs.jsonl> [results.jsonl]}"
OUT="${2:-$(dirname "$JOBS")/results.jsonl}"
META="${OUT%.jsonl}.meta.json"
MAX_JOBS="${CLAUDE_CLI_MAX_JOBS:-20}"
REQ_MODEL="${CLAUDE_CLI_MODEL:-}"
REQ_EFFORT="${CLAUDE_CLI_EFFORT:-}"
TIMEOUT="${CLAUDE_CLI_TIMEOUT:-300}"

command -v claude >/dev/null || { echo "claude not found on PATH" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 1; }
[ -f "$JOBS" ] || { echo "jobs file not found: $JOBS" >&2; exit 1; }

now_ms() { perl -MTime::HiRes=time -e 'printf "%d\n", time*1000'; }
iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- cost safety: environment -------------------------------------------------
API_KEY_WAS_SET=false
[ -n "${ANTHROPIC_API_KEY:-}" ] && API_KEY_WAS_SET=true
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
unset CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY

BASE_URL_HOST="(unset)"
BASE_URL_ACTION="not-set"
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
  BASE_URL_HOST="$(printf '%s' "$ANTHROPIC_BASE_URL" | sed -E 's#^[a-zA-Z]+://##; s#^[^@/]*@##; s#[/:?].*##')"
  case "$BASE_URL_HOST" in
    anthropic.com|*.anthropic.com) BASE_URL_ACTION="kept" ;;
    *) BASE_URL_ACTION="unset"; unset ANTHROPIC_BASE_URL
       echo "[runner] ANTHROPIC_BASE_URL host '$BASE_URL_HOST' is not anthropic.com -> unset for this run" >&2 ;;
  esac
fi
echo "[runner] ANTHROPIC_BASE_URL host: $BASE_URL_HOST ($BASE_URL_ACTION); ANTHROPIC_API_KEY was set: $API_KEY_WAS_SET (unset for run)" >&2

# --- flags (only those this CLI version supports) -----------------------------
HELP="$(claude --help 2>&1 || true)"
has_flag() { printf '%s' "$HELP" | grep -q -- "$1"; }
FLAGS=(-p --output-format stream-json --verbose)
FLAG_NOTES=""
if has_flag '--strict-mcp-config'; then FLAGS+=(--strict-mcp-config --mcp-config '{"mcpServers":{}}'); FLAG_NOTES="$FLAG_NOTES strict-empty-mcp"; fi
if has_flag '--safe-mode'; then FLAGS+=(--safe-mode); FLAG_NOTES="$FLAG_NOTES safe-mode"; fi
if has_flag '--tools <tools'; then FLAGS+=(--tools ""); FLAG_NOTES="$FLAG_NOTES no-tools"; fi
if has_flag '--no-session-persistence'; then FLAGS+=(--no-session-persistence); FLAG_NOTES="$FLAG_NOTES no-session-persistence"; fi
if [ -n "${CLAUDE_CLI_MODEL:-}" ]; then FLAGS+=(--model "$CLAUDE_CLI_MODEL"); fi
if [ -n "${CLAUDE_CLI_EFFORT:-}" ]; then FLAGS+=(--effort "$CLAUDE_CLI_EFFORT"); fi
CLAUDE_VERSION="$(claude --version 2>/dev/null | head -1 || true)"

# Auth summary (no secrets): keep only method/plan/provider style fields.
AUTH_SUMMARY="$(claude auth status 2>/dev/null | grep -i -E 'method|subscription|plan|provider|logged|auth|type' | grep -v -i -E 'token|key' | head -6 | tr '\n' ';' || true)"

# Neutral working dir: no project CLAUDE.md / settings get picked up.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/claude-cli-runner.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
: > "$OUT"

RUN_T0="$(now_ms)"; RUN_STARTED="$(iso_now)"
TOTAL_IN_FILE="$(grep -c . "$JOBS" || true)"
N=0; OK=0; FAIL=0; SUBS=0
while IFS= read -r LINE || [ -n "$LINE" ]; do
  [ -z "$LINE" ] && continue
  if [ "$N" -ge "$MAX_JOBS" ]; then echo "[runner] max jobs ($MAX_JOBS) reached, stopping" >&2; break; fi
  N=$((N+1))
  ID="$(printf '%s' "$LINE" | jq -r '.id')"
  SYS="$(printf '%s' "$LINE" | jq -r '.system // ""')"
  printf '%s' "$LINE" | jq -r '.user // ""' > "$WORK/user.txt"
  SYS_ARGS=()
  [ -n "$SYS" ] && SYS_ARGS=(--system-prompt "$SYS")
  T0="$(now_ms)"; STARTED="$(iso_now)"
  set +e
  ( cd "$WORK" && perl -e 'alarm shift; exec @ARGV' "$TIMEOUT" \
      claude "${FLAGS[@]}" ${SYS_ARGS[@]+"${SYS_ARGS[@]}"} < "$WORK/user.txt" ) > "$WORK/out.jsonl" 2> "$WORK/err.txt"
  RC=$?
  set -e
  T1="$(now_ms)"
  INIT="$(jq -c 'select(.type=="system" and .subtype=="init")' "$WORK/out.jsonl" 2>/dev/null | head -1)"
  RES="$(jq -c 'select(.type=="result")' "$WORK/out.jsonl" 2>/dev/null | tail -1)"
  [ -z "$INIT" ] && INIT='{}'
  [ -z "$RES" ] && RES='{}'
  ERR_TAIL="$(tail -c 400 "$WORK/err.txt" | tr -d '\000')"
  jq -c -n --argjson job "$LINE" --argjson init "$INIT" --argjson res "$RES" \
     --arg rc "$RC" --arg err "$ERR_TAIL" --arg started "$STARTED" --arg finished "$(iso_now)" \
     --arg reqModel "$REQ_MODEL" --arg reqEffort "$REQ_EFFORT" \
     --argjson ms "$((T1-T0))" '
    (if ($res | has("is_error")) then $res.is_error else true end) as $iserr
    | {
      id: $job.id, runId: $job.runId, pipeline: $job.pipeline, stage: $job.stage,
      promptHash: $job.promptHash, provider: "claude-cli",
      ok: (($rc == "0") and ($iserr | not) and (($res.result // "") | length > 0)),
      text: ($res.result // null),
      error: (if ($rc == "0") and ($iserr | not) then null
              else ("exit=" + $rc + " " + ($res.subtype // "") + " " + $err) end),
      claudeModel: ($init.model // null),
      requestedModel: (if $reqModel == "" then null else $reqModel end),
      requestedEffort: (if $reqEffort == "" then null else $reqEffort end),
      apiKeySource: ($init.apiKeySource // null),
      mcpServers: (($init.mcp_servers // []) | length),
      usage: ($res.usage // null),
      notionalCostUsd: ($res.total_cost_usd // null),
      durationMs: $ms, startedAt: $started, finishedAt: $finished
    }' >> "$OUT"
  LAST="$(tail -1 "$OUT")"
  if [ "$(printf '%s' "$LAST" | jq -r '.ok')" = "true" ]; then OK=$((OK+1)); else FAIL=$((FAIL+1)); fi
  [ "$(printf '%s' "$LAST" | jq -r '.apiKeySource')" = "none" ] && SUBS=$((SUBS+1))
  echo "[runner] $ID ok=$(printf "%s" "$LAST" | jq -r .ok) $((T1-T0))ms model=$(printf '%s' "$LAST" | jq -r '.claudeModel') apiKeySource=$(printf '%s' "$LAST" | jq -r '.apiKeySource')" >&2
done < "$JOBS"
RUN_T1="$(now_ms)"

jq -n --arg v "$CLAUDE_VERSION" --arg host "$BASE_URL_HOST" --arg action "$BASE_URL_ACTION" \
   --argjson keyWasSet "$API_KEY_WAS_SET" --arg auth "$AUTH_SUMMARY" --arg flags "$FLAG_NOTES" \
   --argjson maxJobs "$MAX_JOBS" --argjson inFile "${TOTAL_IN_FILE:-0}" --argjson run "$N" \
   --argjson ok "$OK" --argjson fail "$FAIL" --argjson subs "$SUBS" \
   --arg started "$RUN_STARTED" --arg finished "$(iso_now)" --argjson elapsed "$((RUN_T1-RUN_T0))" \
   --arg reqModel "$REQ_MODEL" --arg reqEffort "$REQ_EFFORT" \
   '{runner: "claude_cli_runner.sh/2", claudeVersion: $v,
     requestedModel: (if $reqModel == "" then null else $reqModel end),
     requestedEffort: (if $reqEffort == "" then null else $reqEffort end), baseUrlHost: $host, baseUrlAction: $action,
     anthropicApiKeyWasSet: $keyWasSet, anthropicApiKeyUnset: true, authStatus: $auth, safetyFlags: $flags,
     maxJobs: $maxJobs, jobsInFile: $inFile, jobsRun: $run, ok: $ok, failed: $fail,
     jobsOnSubscription: $subs, startedAt: $started, finishedAt: $finished, elapsedMs: $elapsed}' > "$META"
echo "[runner] done: run=$N ok=$OK failed=$FAIL subscription(apiKeySource=none)=$SUBS elapsed=$((RUN_T1-RUN_T0))ms -> $OUT" >&2
