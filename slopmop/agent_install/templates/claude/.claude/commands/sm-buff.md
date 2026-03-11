# /sm-buff

Triage CI results and review feedback for a pull request.

Usage: Run `sm buff <PR_NUMBER>` after CI completes or review feedback lands.

1. Run `sm buff <PR_NUMBER>`.
2. Summarize the triage output — what passed, what failed, what needs attention.
3. Propose a concrete remediation plan for each actionable item.

Never mark a failing gate as resolved without actually fixing it.
