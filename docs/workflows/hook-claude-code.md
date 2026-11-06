# `hook claude-code` (run by Claude Code, never by hand)

```mermaid
flowchart TD
    start(["stdin: hook JSON"]) --> guard{"NOESIS_HOOK=1?<br/>(curator's own run)"}
    guard -->|yes| quiet(["return: print nothing, exit 0"])
    guard -->|no| parse{"ClaudeCodeHookPayload<br/>valid JSON?"}
    parse -->|no| quiet
    parse -->|yes| route{"route(payload)<br/>Capture inbound ACL"}
    route -->|"PostToolUse, Bash, really git commit"| rc[RecordCommitCommand]
    route -->|Stop| fl["FlushCaptureCommand final=false"]
    route -->|SessionEnd| ff["FlushCaptureCommand final=true"]
    route -->|anything else| quiet
    route -->|"cd DIR && git commit / git -C DIR commit"| hint["worktree_hint = DIR"] --> rc
    rc --> res["ResolveSessionIdentityHandler<br/>payload id -> stored id in this repo"] --> rch[RecordCommitHandler]
    rch --> g0{session enabled?}
    g0 -->|no| j1["journal: not_opted_in"]
    g0 -->|yes| git["GitCliVcsReader: common dir, every worktree's HEAD<br/>(git rev-parse, worktree list, one git log)"]
    git --> cand{"worktree HEADs that moved since the baseline<br/>and were committed within 120 s"}
    cand -->|none| j3["journal: no_new_commit"]
    cand -->|one| pend["session.pending += commit (with branch, worktree)"] --> j2["journal: marked"]
    cand -->|several| narrow{"worktree_hint names one?"}
    narrow -->|yes| pend
    narrow -->|no| j4["journal: ambiguous_worktree<br/>nothing recorded, stays a candidate"]

    fl --> fh[FlushCaptureHandler]
    ff --> fh
    fh --> s1{enabled?} -->|no| k1[not_opted_in]
    s1 -->|yes| s2{pending commits?} -->|no| k2[no_pending]
    s2 -->|yes| s3{"outside debounce?<br/>(final skips it)"} -->|no| k3[debounced]
    s3 -->|yes| s4{"significant size?<br/>files >= MIN_FILES or lines >= MIN_LINES"}
    s4 -->|"no, not final"| k4["trivial: keep waiting"]
    s4 -->|"no, final"| k5["trivial_dropped: pending cleared"]
    s4 -->|yes| s5{transcript readable?} -->|no| k6[transcript_unreadable]
    s5 -->|yes| s6{real work in this turn?} -->|no| k7[no_real_work]
    s6 -->|yes| mkbrief["build WorkBriefContract<br/>commits, branch, diff stat, goal, excerpt"]
    mkbrief --> mode{session mode}
    mode -->|dry-run| dry["DryRunPublisher: write brief file only"]
    mode -->|live| live["DetachedProcessPublisher: write brief file + spawn curate"]
    dry --> ok["handed_over: cursor moves, pending cleared"]
    live --> ok
    live -.->|spawn failed| fail["handover_failed / abandoned"]

    errors(["any unexpected error at any step:<br/>append to state/capture/hook-errors.log, still exit 0"])
```

Every outcome (`k1`..`k7`, `ok`, `fail`) is a journal line, which is what `capture runs` shows.

Cost: each commit hook runs a few git calls (`rev-parse --git-common-dir`, `worktree list
--porcelain`, one `git log` over the HEADs, then the commit's own `rev-parse`/`log`/`show`),
about ten milliseconds in total. The hook compares worktree HEADs with the baseline stored in
the session (`observed_heads`), so it finds the commit wherever it was made; the command text is
only a tiebreaker. A flush takes the repository name, path and branch from the recorded commits.

Back to [workflows](README.md).
