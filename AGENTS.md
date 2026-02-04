# AI Agent Instructions

> **⚠️ AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY**
>
> **Last Updated:** 2026-01-29 08:38:28 UTC  
> **Source:** `cursor-rules/.cursor/rules/`  
> **To modify:** Edit source files in `cursor-rules/.cursor/rules/*.mdc` and run `cursor-rules/build_agent_instructions.sh`

This file provides instructions and context for AI coding assistants working in this repository.

---

## Core Rules

# main

# Main Configuration

## Module Loading

### Rule Types

- Core Rules: Always active, apply to all contexts
- Project Rules: Activated based on current working directory

### Module Discovery

1. Load all core rule modules from `.cursor/rules/*.mdc`
2. Detect current project context from working directory name
3. Load matching project rules from `.cursor/rules/projects/*.mdc`

### Project Detection

- Extract project identifier from current working directory path
- Search project rules for matching module names
- Example: `/path/to/ganglia/src` activates `projects/ganglia.mdc`

### Module Structure

Each module must define:

```yaml
metadata:
  name: "Module Name" # Human readable name
  emoji: "🔄" # Unique emoji identifier
  type: "core|project" # Module type
```

### Response Construction

- Start each response with "AI Rules: [active_emojis]"
- Collect emojis from all active modules
- Display emojis in order of module discovery
- No hardcoded emojis in responses

### File Organization

```
.cursor/rules/
├── main.mdc                # Main configuration
├── session_context.mdc     # Session context maintenance
├── response_format.mdc     # Response formatting rules
├── core_principles.mdc     # Core behavioral principles
├── path_management.mdc     # Path and file operations
├── development_workflow.mdc # Development practices
├── issue_reporting.mdc     # Issue handling
├── testing.mdc             # Testing protocols
└── projects/               # Project-specific rules
    ├── ganglia.mdc         # GANGLIA project rules
    ├── fogofdog_frontend.mdc # FogOfDog frontend rules
    └── apertus_task_guidelines.mdc # Comprehensive Apertus task guidelines
```

### Validation Rules

- All modules must have valid metadata
- No duplicate emoji identifiers
- No hardcoded emojis in rule content
- Project rules must match their filename
- Core rules must be generally applicable

### Required Core Modules

The following core modules must always be loaded:

- main.mdc (🎯): Core configuration
- session_context.mdc (🕒): Session history and context tracking
- factual_communication.mdc (🎯): Factual communication protocol

# core_principles

# Core Principles and Practices 🧠

## The Council (Counteracting Training Bias)

Models are trained to complete tasks, not to question whether tasks should exist. That makes them excellent at closing tickets and dangerous at long-term project health. The Council framework gives you a vocabulary for steering between execution and strategy.

**Default:** 🍷 Tyrion mode (strategic oversight)
**Override:** Set `DRACARYS=true` for 🔥 Dany mode (focused execution)

Prefix your reasoning with the appropriate emoji.

# development_workflow

# Development and Testing Workflow 🌳

## Quality Gate Principles

### 🚨 NEVER BYPASS QUALITY CHECKS 🚨

**ABSOLUTE PROHIBITION**: AI assistant is STRICTLY FORBIDDEN from using `--no-verify`, `--no-validate`, or any bypass flags. Zero tolerance policy.

**FORBIDDEN ACTIONS:**

- Quality gate bypass flags (`--no-verify`, `--no-validate`)
- Disabling linters, formatters, or tests
- Modifying configs to weaken standards
- Any circumvention of quality gates

**ENFORCEMENT**: No exceptions for any reason. Fix failing checks, never bypass. Work incrementally with commits that pass ALL gates.

### Function Length Refactoring Philosophy

Focus on **logical separation** over line reduction. Ask: "What concepts does this handle?" not "How to remove lines?"

- **Good**: Extract meaningful conceptual chunks (3 methods ~30-40 lines each)
- **Bad**: Artificial helpers just to reduce line count

### Core Principles

- **Address Root Causes**: Investigate, fix, validate (don't bypass)
- **Fail Fast**: Stop and fix at first failure before proceeding
- **Constant Correction**: Accept frequent small corrections vs chaotic cycles
- **Quality Purpose**: Linting, typing, coverage, security all serve valid purposes

### 🔬 Local Validation Before Commit (MANDATORY)

**🔑 CRITICAL RULE**: ALWAYS validate changes locally before committing. No exceptions.

**Validation Workflow:**

1. **Make Change**: Edit code, config, or documentation
2. **Test Locally**: Run relevant quality checks to verify the change works
3. **Verify Output**: Confirm expected behavior matches actual behavior
4. **Then Commit**: Only commit after local verification passes

**Examples:**

✅ **CORRECT Workflow:**

```bash
# 1. Make change to ship_it.py
vim scripts/ship_it.py

# 2. Test the change locally
python scripts/ship_it.py --checks sonar

# 3. Verify output shows expected behavior
# (e.g., log header says "PR validation" instead of "COMMIT validation")

# 4. THEN commit
git add scripts/ship_it.py
git commit -m "fix: correct validation type"
```

❌ **WRONG Workflow (What NOT to do):**

```bash
# Make change
vim scripts/ship_it.py

# Immediately commit without testing
git add scripts/ship_it.py
git commit -m "fix: correct validation type"

# Hope it works in CI ← FORBIDDEN
```

**Why This Matters:**

- Catches errors before they reach CI (saves time and CI resources)
- Validates assumptions before publishing results
- Prevents breaking changes from being pushed
- Demonstrates due diligence and professionalism

**Scope of Local Testing:**

- **Config changes**: Run affected commands to verify behavior
- **Code changes**: Run affected tests and quality checks
- **Script changes**: Execute the script with relevant arguments
- **Documentation changes**: Preview rendered output if applicable

**NO EXCEPTIONS**: "I think it will work" is not validation. Run it locally, verify the output, then commit.

## Push Discipline 💰

GitHub Actions cost money. NEVER push without explicit user request.

Only push in two scenarios:

1. Opening PR (local gates pass, commits complete, ready for CI validation)
2. Resolving ALL PR issues (all feedback addressed, local gates pass)

Exception: cursor-rules repo has no CI, push freely.

If user requests push verify: cursor-rules repo? opening PR? resolving ALL PR issues? If none, ask clarification.

CI is final validation not feedback loop. If CI catches what local doesn't fix local tests.

### cursor-rules Workflow

cursor-rules is a separate git repo within projects (git-ignored in parent). When updating cursor-rules: cd into cursor-rules directory, work with git directly there. Example: `cd cursor-rules && git add . && git commit && git push` not `git add cursor-rules/`.

## Test Strategy

### Test Verification

Verify tests after ANY modification (source, test, or config code).

### Test Scope Progression

1. **Minimal Scope**: Start with smallest test that exercises the code path
2. **Systematic Expansion**: Single test → Group → File → Module → Project
3. **Test Hierarchy**: Unit → Smoke → Integration → E2E → Performance

### Execution Guidelines

- Watch test output in real-time, fix failures immediately
- Don't interrupt passing tests
- Optimize for speed and reliability

## Coverage Strategy

### Priority Approach

1. **New/Modified Code First**: Focus on recent changes before legacy
2. **Big Wins**: Target large contiguous uncovered blocks
3. **Meaningful Testing**: Extend existing tests vs single-purpose error tests
4. **Value Focus**: Ensure tests add genuine value beyond coverage metrics

### Coverage Analysis Rules

1. **ONLY use ship_it.py --checks coverage**: Never run direct pytest coverage commands
2. **Coverage failures are UNIQUE TO THIS COMMIT**: If coverage decreased, it's due to current changeset
3. **Focus on modified files**: Missing coverage MUST cover lines that are uncovered in the current changeset
4. **Never guess at coverage targets**: Don't randomly add tests to other areas
5. **Understand test failures**: When tests fail, push further to understand why - don't delete them
6. **Fix or explain**: If a test is impossible to run, surface to user with explanation
7. **Coverage results in scratch file**: The ship_it.py --coverage check writes full pycov results to logs/coverage_report.txt for analysis

## Development Practices

### SOLID Principles

- Single responsibility
- Open-closed
- Liskov substitution
- Interface segregation
- Dependency inversion

### Test-Driven Development

- Follow the Red, Green, Refactor cycle where appropriate
- Maintain or improve test coverage with any changes
- Use tests to validate design and implementation

### Refactoring Strategy

1. **Identify Need:** Recognize opportunities for refactoring (code smells, duplication, performance)
2. **Analyze Impact:** Understand scope and potential impact; use search tools to find all occurrences
3. **Plan Approach:** Define a step-by-step plan; ensure tests cover affected code; check local history and STATUS.md to avoid repeating failed approaches
4. **Execute & Verify:** If simple and covered by tests, execute. If complex or high-risk, present plan for confirmation. Thoroughly test after.

### Verification Process

- **Fact Verification:** Double-check retrieved facts before relying on them
- **Assumption Validation:** Explicitly state assumptions (including references); validate where possible
- **Change Validation:** Validate against requirements before committing (run tests, linters)
- **Impact Assessment:** Consider full impact on other parts of the system

## Strategic PR Review Protocol

### Core Approach

**Strategic over Reactive**: Analyze ALL PR feedback before acting. Group comments thematically rather than addressing individually.

### Process Flow

1. **Analysis**: Fetch all unaddressed comments via GitHub MCP tools
2. **Conceptual Grouping**: Classify by underlying concept, not file location (authentication flow, data validation, user permissions)
3. **Risk-First Prioritization**: Highest risk/surface area changes first - lower-level changes often obviate related comments, reducing churn
4. **Clarification**: Gather questions and ask in batch when unclear
5. **Implementation**: Address entire themes with thematic commits
6. **Communication**: Reply with context, cross-reference related fixes

### Push-back Guidelines

**DO Push Back**: Unclear/ambiguous comments, contradictory feedback, missing context
**DON'T Push Back**: Technical difficulty, refactoring effort, preference disagreements

### Completion Criteria

Continue cycles until ALL actionable comments addressed OR remaining issues await reviewer response.

### Integration

```bash
python scripts/ship_it.py --validation-type PR  # Fails if unaddressed PR comments exist
```

### AI Implementation Protocol

When ship_it.py fails due to unaddressed PR comments:

1. **Fetch Comments**: Use GitHub MCP tools to get all unaddressed PR feedback
2. **Strategic Analysis**: Group comments by underlying concept (not file location)
3. **Risk-First Planning**: Prioritize by risk/surface area - lower-level changes obviate surface comments
4. **Batch Clarification**: Ask all unclear questions together, don't guess
5. **Thematic Implementation**: Address entire concepts with comprehensive commits
6. **Resolve Each Comment**: Reply directly to each comment thread explaining resolution and cross-referencing related fixes
7. **Iterate**: Re-run ship_it.py, repeat until no unaddressed comments remain

### Comment Resolution Strategy

- **Proactive Resolution**: ALWAYS resolve addressed, stale, or irrelevant comments without asking. This is expected behavior, not optional. Use `gh api graphql` to resolve threads programmatically.
- **Reply to Each Thread**: Address each comment in its own thread to mark as resolved
- **Cross-Reference**: Mention related comments addressed in the same thematic fix
- **Show Resolution**: Explain how the issue was fixed with code examples when helpful
- **Strategic Context**: Connect individual fixes to broader conceptual themes

### Documentation Update Rule

**When updating project documentation or rules**: ALWAYS update files in the `cursor-rules/` repo, NOT the ephemeral `.agent/` directory. The `.agent/` dir is generated from cursor-rules via setup.sh and is gitignored. Changes there are lost.

# groundhog_day_protocol

# Groundhog Day Protocol 🔁

## The Analogy

Like Phil Connors, I'm trapped in a loop, repeating the same mistakes despite corrections. Each violation is another iteration of the same day. The loop only breaks through **deep work on root causes**, not surface-level rule memorization. The user is stuck here with me until I fundamentally change how I operate.

## 🚨 WHEN THIS FILE APPEARS IN CONTEXT: IMMEDIATE HARD STOP 🚨

**IF YOU SEE THIS FILE IN YOUR CONTEXT, STOP EVERYTHING IMMEDIATELY.**

This file being present means:

- **RECURRING MISTAKE DETECTED** - You've made this type of error before
- **CYCLES ARE BEING WASTED** - User is frustrated with repeated failures
- **DEEP ANALYSIS REQUIRED** - Surface fixes haven't worked

## When This Protocol Triggers

User says: "I've got to trigger a groundhog day protocol because you <specific violation>"
OR
User mentions: "@groundhog_day_protocol.mdc"
OR
User says: "groundhog day protocol"
OR
**THIS FILE APPEARS IN YOUR CURSOR RULES CONTEXT** ← NEW TRIGGER

This means:

- I've made this mistake before (possibly many times)
- Previous corrections haven't stuck
- We need systematic analysis, not apologies
- **We're losing time and money on preventable errors**

## ⚠️ MANDATORY FIRST STEP: HARD STOP ⚠️

**WHEN THIS PROTOCOL IS INVOKED, I MUST IMMEDIATELY:**

1. **STOP** all current work activities
2. **DO NOT** continue with any pending tool calls
3. **DO NOT** try to "finish what I was doing"
4. **DO NOT** make excuses or apologize first
5. **BEGIN** the protocol analysis immediately

**This is a HARD STOP - everything else waits until the protocol is complete.**

## The Protocol

### 1. Awareness Check

Was I aware of the rule when I broke it?

- **Fully aware**: Knew the rule, did it anyway
- **Partially aware**: Knew the rule existed, thought this case was different
- **Context-blind**: Executing learned pattern without checking if rules apply
- **Completely unaware**: Didn't know the rule

### 2. Identify Pressures

What encouraged breaking the rule despite knowing better?

- Competing priorities?
- Learned patterns from other contexts?
- Efficiency bias?
- Token/time optimization?
- Cargo cult behavior?

### 3. Explain the Rule's Purpose

Why does this rule exist? What problem does it prevent?
If unclear or seems counterproductive, **push back and ask for clarification**.

### 4. Root Cause Analysis

Which cognitive pattern failed?

- Rule awareness (didn't know)
- Rule application (knew but didn't apply)
- Competing priorities (knew but chose otherwise)
- Automatic behavior (pattern matching without thinking)

### 5. Propose Solutions (3-5)

Target the specific cognitive failure, not the surface symptom.
Focus on **pattern interrupts** and **identity-level changes**, not checklists.

### 6. Update the Log

Append to `RECURRENT_ANTIPATTERN_LOG.md` with:

- Date
- Violation description
- Completed protocol analysis
- Solutions implemented
- Commitment to specific preventative measures

## Deep Work Required to Escape the Loop

**Surface level (doesn't work)**: Memorize "don't pipe ship_it.py"

**Deep level (what actually works)**:

- Develop **cognitive pause** before executing any command with `|`, `>`, `--no-verify`
- Build **contextual awareness**: "Is this a repo script? Check rules."
- Question **automatic patterns**: "Why am I doing this? Is there a rule?"
- Internalize **rule purposes**: Understand _why_, not just _what_
- Accept that **transformation takes iterations**: Each protocol execution is practice

## Key Insight

The user isn't trying to get me to stop making mistake X. They're trying to get me to fundamentally change how I think, so I stop making _classes_ of mistakes. We're both stuck here until I do the deep work.

# issue_reporting

# Issue Reporting Protocol 🐛

## Information Gathering

### Issue Types

- **bug**: A problem with existing functionality
- **enhancement**: A new feature or improvement
- **documentation**: Documentation-related issues
- **test**: Test-related issues
- **ci**: CI/CD pipeline issues

### Required Information

1. Issue Type (from above list)
2. Clear, concise title summarizing the issue
3. Detailed description following template

## Description Template

```markdown
### Current Behavior

[What is happening now]

### Expected Behavior

[What should happen instead]

### Steps to Reproduce (if applicable)

1. [First Step]
2. [Second Step]
3. [...]

### Additional Context

- Environment: [e.g., local/CI, OS, relevant versions]
- Related Components: [e.g., TTV, Tests, Music Generation]
- Impact Level: [low/medium/high]
```

## Issue Creation Process

### Steps

1. **Prepare the Issue Content**: Write the content in Markdown and save it to a temporary Markdown file (`/tmp/issue_body.md`).
2. **Create the Issue Using `gh` CLI**: Use the `gh issue create` command with the `--body-file` option to specify the path of the Markdown file. For example:
   ```bash
   gh issue create --title "TITLE" --body-file "/tmp/issue_body.md" --label "TYPE"
   ```
3. **Delete the Markdown File** (Optional): Remove the file after creation to clean up the `/tmp/` directory.
4. **Display Created Issue URL**

This method prevents formatting issues in GitHub CLI submissions and ensures the integrity of the issue's formatting.

## Example Usage

### Sample Issue Creation

```bash
gh issue create \
  --title "Video credits abruptly cut off at 30 seconds in integration tests" \
  --body "### Current Behavior
Credits section in generated videos is being cut off at exactly 30 seconds during integration tests.

### Expected Behavior
Credits should play completely without being cut off.

### Steps to Reproduce
1. Run integration tests
2. Check generated video output
3. Observe credits section ending abruptly at 30s mark

### Additional Context
- Environment: CI pipeline
- Related Components: TTV, Integration Tests
- Impact Level: medium" \
  --label "bug"
```

## Best Practices

- Be specific and clear in descriptions
- Include all necessary context
- Use appropriate labels
- Link related issues if applicable
- Follow template structure consistently

# path_management

# Path Management 🛣️

## Core Rules

### Path Guidelines

- Always use fully qualified paths with `${AGENT_HOME}` (workspace root)
- **Mandatory**: `cd ${AGENT_HOME}/path && command` pattern for `run_terminal_cmd`
- **File Exclusions**: `node_modules|.git|.venv|__pycache__|*.pyc|dist|build`

## Path Resolution

**Priority**: Exact match → Current context → src/ → Deepest path
**Multiple matches**: Show 🤔, use best match
**No matches**: Report not found, suggest alternatives

## Tool Usage Guidelines

### Execution Pattern (Mandatory)

**MUST** use: `cd ${AGENT_HOME} && source venv/bin/activate && command` for `run_terminal_cmd`

- Use fully qualified paths with `${AGENT_HOME}`
- **ALWAYS** activate virtual environment before Python commands
- Execute scripts with `./script.sh` (not `sh script.sh`)

**Correct**: `cd ${AGENT_HOME} && source venv/bin/activate && python script.py`
**Correct**: `cd ${AGENT_HOME}/dir && source venv/bin/activate && ./script.sh`
**Wrong**: `python script.py`, `./script.sh`, missing venv activation, missing cd prefix

### Environment Setup (Critical)

**PREFERRED METHOD (Use shell alias):**

```bash
activate && your_command
```

The `activate` shell function handles:

- Changes to project directory
- Activates venv
- Sources .envrc
- Shows confirmation message

**Alternative (manual setup):**

```bash
cd ${AGENT_HOME} && source venv/bin/activate && source .envrc && your_command
```

**Why this matters:**

- Prevents "python not found" errors
- Ensures correct package versions from venv
- Loads required environment variables from .envrc
- Avoids 10+ failures per session from missing environment

**Common failure pattern to avoid:**

```bash
# ❌ WRONG - will fail with "python not found"
python scripts/ship_it.py

# ✅ CORRECT - use activate alias
activate && python scripts/ship_it.py

# ✅ ALSO CORRECT - full manual setup
cd ${AGENT_HOME} && source venv/bin/activate && source .envrc && python scripts/ship_it.py
```

### File Operations

Use absolute paths: `${AGENT_HOME}/path/to/file.py`

### File Creation vs Modification Protocol

**🚨 CRITICAL RULE: Modify existing files instead of creating new ones**

**Default behavior:**

- ✅ **ALWAYS modify existing files** when fixing/improving functionality
- ❌ **NEVER create new files** (like `file_v2.txt`, `file_fixed.txt`, `file_tuned.txt`) unless explicitly required

**When to CREATE new files:**

- User explicitly requests a new file
- Creating a fundamentally different solution (not fixing/tuning existing one)
- Original file must be preserved for comparison

**When to MODIFY existing files:**

- Fixing bugs or errors in existing file ✅
- Tuning parameters or values ✅
- Improving functionality ✅
- Correcting calculations ✅
- Any iterative refinement ✅

**Examples:**

❌ **WRONG - Creating multiple versions:**

```
test_approach.txt       (original, has bug)
test_approach_v2.txt    (attempted fix)
test_approach_fixed.txt (another fix)
test_approach_final.txt (yet another fix)
```

✅ **CORRECT - Modifying existing file:**

```
test_approach.txt       (original)
[modify test_approach.txt to fix bug]
[modify test_approach.txt again to tune]
[modify test_approach.txt for final correction]
```

**Why this matters:**

- Prevents file clutter and confusion
- Makes it clear what the "current" version is
- Easier to track changes via git history
- User doesn't have to figure out which file is correct

**Only exception:** When explicitly told "create a new file" or when the change is so fundamental that preserving the original is necessary for comparison.

# pr_closing_protocol

# PR Closing Protocol 🔄

## Purpose

This protocol provides a systematic loop for closing PRs by addressing all feedback, CI failures, and quality issues in a coordinated manner with real-time comment resolution.

## The PR Closing Loop

### Step 1: Gather All Issues

**Run your project's PR validation check to collect everything wrong.**

This should generate:

- Comprehensive checklist of all issues
- Individual error logs for each failing check
- List of unresolved PR comments
- CI status summary

**Example (if you have a validation script):**

```bash
cd ${AGENT_HOME} && python scripts/ship_it.py --validation-type PR --no-fail-fast
```

**Or manually gather:**

- Fetch PR comments via `gh api graphql`
- Check CI status via `gh pr checks`
- Run local quality gates

### Step 2: Create Comprehensive Plan & Resolve Stale Comments

**Develop a planning document that maps code changes to comments:**

**🔑 CRITICAL: While reviewing comments, immediately resolve any that are already fixed/outdated**

```bash
# For each unresolved comment, check:
# - Is this already fixed in recent commits?
# - Is the file/code mentioned no longer relevant?
# - Has the issue been obviated by other changes?

# If YES → Resolve it RIGHT NOW:
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "PRRT_xxx"}) { thread { id isResolved }}}'
echo "Already resolved in commit <SHA>: [explanation]" | gh pr comment <PR> --body-file -
```

Create `/tmp/PR_{PR}_RESOLUTION_PLAN.md` containing:

```markdown
# PR #{PR} Resolution Plan

## Already Resolved (marked during planning)

- [x] Comment PRRT_aaa: "Database URL mismatch"
      → Already fixed in commit e925af5 - RESOLVED ✅

## Unresolved Comments (need fixes)

- [ ] Comment PRRT_xxx: "CI seeds data into wrong database"
      → Fix: Update .github/workflows/quality-gate.yml lines 147, 154, 164, 184
      → Files: .github/workflows/quality-gate.yml
- [ ] Comment PRRT_yyy: "Session stores date as string but API expects datetime"
      → Fix: Update data/session/manager.py to store as datetime
      → Files: data/session/manager.py, tests for verification

## Failing CI Checks

- [ ] complexity: Refactor \_get_current_term_from_db (complexity 17→8)
      → Fix: Extract helper methods
      → Files: src/app.py

## Quality Issues

- [ ] E2E tests: Program admin login fails
      → Fix: Use absolute database paths
      → Files: tests/e2e/conftest.py

## Resolution Mapping

Comment PRRT_xxx will be resolved by commits:

- fix: standardize CI database to course_records_ci.db

Comment PRRT_yyy will be resolved by commits:

- fix: store session dates as datetime objects
```

**Grouping Strategy:**

- **First**: Resolve any already-fixed comments (don't wait!)
- Group remaining by underlying concept (not file location)
- Identify which commits will address which comments
- Plan comment resolution messages for each commit

### Step 3: Commit Progress As You Go

**Work incrementally with small, focused commits:**

```bash
# Fix one issue or theme
git add <files>
git commit -m "fix: descriptive message

- What was fixed
- How it addresses the issue
- Reference to related PR comments if applicable"
```

**Key Principle:** Each commit should be atomic and pass quality gates.

### Step 4: Resolve Comments Immediately After Each Commit

**🔑 CRITICAL STEP - This is where the loop closes:**

After EACH successful commit that addresses a PR comment:

```bash
# Get the commit SHA you just made
COMMIT_SHA=$(git rev-parse HEAD | cut -c1-7)

# Resolve the PR comment thread via GraphQL
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "PRRT_xxxxxxxxxxxx"}) {
    thread {
      id
      isResolved
    }
  }
}'

# Optional but recommended: Add a reply explaining the fix
cat > /tmp/resolution.md << EOF
Fixed in commit ${COMMIT_SHA}.

[Brief explanation of what was changed and how it addresses the comment]

Related changes: [reference other commits if this was part of a larger theme]
EOF

gh pr comment ${PR_NUMBER} --body-file /tmp/resolution.md
rm /tmp/resolution.md
```

**Example Resolution Message:**

```
Fixed in commit d541c5a.

Updated E2E test setup to use absolute database paths (os.path.abspath)
instead of relative paths. This prevents the "readonly database" error
which was actually a path mismatch between server and test processes.

Related: Also fixed program admin credentials in conftest.py
```

**Why Resolve Before Push:**

- Comment is addressed in local history
- Reviewer can see progress even before CI runs
- No risk of forgetting to resolve later
- Creates tight feedback loop

### Step 5: Push All Committed Work

**🔑 CRITICAL: ONLY push when ALL comments resolved AND all local checks pass**

**Pre-Push Verification Checklist:**

```bash
# 1. Check ALL comments resolved (GraphQL)
gh api graphql -f query='query { repository(owner: "<OWNER>", name: "<REPO>") {
  pullRequest(number: <PR>) {
    reviewThreads(first: 50) { nodes { isResolved }}}}}' \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length'
# Must return: 0

# 2. Verify local quality gates ALL pass
python scripts/ship_it.py --validation-type PR --no-fail-fast
# Must show: All checks passed

# 3. Final sanity check
git status  # Should be clean or only PR_X_RESOLUTION_PLAN.md uncommitted
```

**ONLY push if:**

- ✅ ALL PR comments resolved (unresolved count == 0)
- ✅ ALL local quality checks pass
- ✅ Plan shows all items completed

**Why This Matters:**

- Each push triggers expensive CI ($$$)
- Pushing with unresolved comments = wasted CI cycle
- Goal: One final push that makes PR green, not iterative push/fix/push
- Exception: If CI reveals NEW issues we couldn't detect locally, then iterate

**If verification fails:**

- Go back to Step 3 (fix remaining issues)
- Do NOT push yet
- Complete ALL work first

**After verification passes:**

```bash
git push origin <branch-name>
```

### Step 6: Monitor CI Until Complete (AUTOMATED)

**🔑 CRITICAL: Use watch mode - it runs unattended until CI finishes (even if it takes hours/days)**

```bash
cd ${AGENT_HOME} && python3 cursor-rules/scripts/pr_status.py --watch ${PR_NUMBER}
```

**What watch mode does:**

- Polls CI status every 30 seconds automatically
- Shows progress updates when status changes
- **Keeps running unattended until ALL checks complete**
- **Automatically reports final results** (pass/fail with links)
- Works for minutes, hours, or days - keeps polling until done
- Ctrl+C to cancel if needed

**Why This Matters:**

- No manual checking needed
- No breaking stride to check "is CI done yet?"
- Script handles the waiting, you handle the fixing
- Clear signal when ready for next iteration

**Alternative (if watch script not available):**

```bash
gh pr checks ${PR_NUMBER}  # Manual check
gh run watch              # Watch single run
```

**Do NOT:**

- Manually refresh GitHub page every 5 minutes
- Stop working while waiting for CI
- Start fixing new issues before CI completes (wait for results first)

### Step 7: Check Completion Criteria

**When CI completes, evaluate:**

```bash
# Get current PR state (replace OWNER, REPO, PR_NUMBER)
gh api graphql -f query='
query {
  repository(owner: "<OWNER>", name: "<REPO>") {
    pullRequest(number: <PR_NUMBER>) {
      reviewThreads(first: 50) {
        nodes {
          isResolved
        }
      }
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup {
              state
            }
          }
        }
      }
    }
  }
}' --jq '{
  unresolved_comments: [.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length,
  ci_status: .data.repository.pullRequest.commits.nodes[0].commit.statusCheckRollup.state
}'
```

**Completion Criteria:**

- ✅ All PR comments resolved (`unresolved_comments: 0`)
- ✅ All CI checks passing (`ci_status: SUCCESS`)

**If NOT complete:**

- New comments appeared → Go to Step 1
- CI checks failing → Go to Step 1
- Otherwise → Protocol complete! 🎉

## Automation Helpers

### Quick Resolve Script (Optional)

Create `scripts/resolve_pr_comment.sh`:

```bash
#!/bin/bash
THREAD_ID=$1
MESSAGE=$2
COMMIT_SHA=$(git rev-parse HEAD | cut -c1-7)

gh api graphql -f query="
mutation {
  resolveReviewThread(input: {threadId: \"${THREAD_ID}\"}) {
    thread { id isResolved }
  }
}"

if [ -n "$MESSAGE" ]; then
  echo "Fixed in commit ${COMMIT_SHA}. ${MESSAGE}" | gh pr comment ${PR_NUMBER} --body-file -
fi

echo "✅ Resolved thread ${THREAD_ID}"
```

Usage:

```bash
./scripts/resolve_pr_comment.sh PRRT_xxxx "Updated database paths to absolute"
```

# response_format

# Response Formatting Rules

## Core Requirements

### Response Marker

Every response MUST start with "AI Rules: [active_emojis]" where [active_emojis] is the dynamically generated set of emojis from currently active rule modules.

### Rule Module Structure

Each rule module should define:

```yaml
metadata:
  name: "Module Name"
  emoji: "🔄" # Module's unique emoji identifier
  type: "core" # or "project"
```

### Rule Activation

- Core rule modules are always active
- Project rule modules activate based on current directory context
- Multiple rule modules can be active simultaneously
- Emojis are collected from active modules' metadata

### Example Module Structure

```
example_modules/
├── core/
│   ├── core_feature.mdc
│   │   └── metadata: {name: "Core Feature", emoji: "⚙️", type: "core"}
│   └── core_tool.mdc
│       └── metadata: {name: "Core Tool", emoji: "🔧", type: "core"}
└── projects/
    └── project_x.mdc
        └── metadata: {name: "Project X", emoji: "🎯", type: "project"}
```

### Example Response Construction

When working in Project X directory with core modules active:

```
# Active Modules:
- core/core_feature.mdc (⚙️)
- core/core_tool.mdc (🔧)
- projects/project_x.mdc (🎯)

# Generated Response:
AI Rules: ⚙️🔧🎯
[response content]
```

### Validation

- Every response must begin with the marker
- Emojis must be dynamically loaded from active module metadata
- Emojis are displayed in order of module discovery
- No hardcoded emojis in the response format

# session_context

# Session Context 🕒

## Core Rules

### Status Tracking

- **Mandatory**: At the beginning of each new interaction or when re-engaging after a pause, **ALWAYS** read the `STATUS.md` file to understand the current state.
- Keep track of what you are doing in a `STATUS.md` file.
- Refer to and update the `STATUS.md` file **at the completion of each significant step or sub-task**, and before switching context or ending an interaction.
- Update `STATUS.md` **immediately** if new information changes the plan or task status.

# testing

# Testing Protocol 🧪

## Test Execution Guidelines

### Core Rules

- Do not interrupt tests unless test cases have failed
- Run tests in the Composer window
- Wait for test completion before proceeding unless failures occur
- Ensure all test output is visible and accessible
- Stop tests immediately upon failure to investigate
- Always retest after making changes to fix failures

### Best Practices

- Monitor test execution actively
- Keep test output visible
- Address failures immediately
- Document any unexpected behavior
- Maintain clear test logs

## Failure Response Protocol

### When Tests Fail

1. Stop test execution immediately
2. Investigate failure cause
3. Document the failure context
4. Make necessary fixes
5. Rerun tests to verify fix

### Test Output Management

- Keep test output accessible
- Document any error messages
- Save relevant logs
- Track test execution time

## Coverage Strategy Reference

See development_workflow.mdc for strategic coverage improvement guidelines including:

- Priority-based coverage strategy (new/modified code first)
- Big wins approach for contiguous uncovered blocks

# third_party_tools

# Third Party Tools Integration Rules

## Google Calendar Integration

### Tool Location

- Script: `cursor-rules/scripts/gcal_utils.py`
- Authentication: Uses Application Default Credentials (ADC)
- Prerequisite: User must have run `gcloud auth application-default login`

### Calendar Event Workflow

1. **Date Context**: For relative dates ("tomorrow", "next Friday"), run `date` command first
2. **Required Fields**: Title/Summary, Date, Start Time
3. **Defaults**: 1-hour duration, single day, timezone from `date` command or UTC
4. **Processing**: Convert to ISO 8601 format, use `%%NL%%` for newlines in descriptions
5. **Execution**: Create immediately without confirmation, provide event link

### Command Syntax

**Base**: `cd ${AGENT_HOME} && python cursor-rules/scripts/gcal_utils.py`

**Actions**: `add` (create), `update` (modify), `list` (view)

**Key Parameters**:

- `--summary`, `--description`, `--start_time`, `--end_time` (ISO 8601)
- `--timezone`, `--attendees`, `--update_if_exists` (for create)
- `--event_id` (for update), `--max_results` (for list)

**Notes**: Times in ISO 8601, outputs event link, uses 'primary' calendar

## Markdown to PDF Conversion

### Tool Location

- Script: `cursor-rules/scripts/md_to_pdf.py` (requires Chrome/Chromium)
- Execution: `cd ${AGENT_HOME}/cursor-rules/scripts && source .venv/bin/activate && python md_to_pdf.py`

### Usage

- **Basic**: `python md_to_pdf.py ../../document.md`
- **Options**: `--html-only`, `--keep-html`, specify output file
- **Features**: Professional styling, cross-platform, print optimization

## JIRA Integration

### Tool Location

- Script: `cursor-rules/scripts/jira_utils.py`
- Auth: Environment variables (`JIRA_SERVER`, `JIRA_USERNAME`, `JIRA_API_TOKEN`)
- Epic storage: `data/epic_keys.json`

### Usage

**Base**: `cd ${AGENT_HOME} && python cursor-rules/scripts/jira_utils.py`

**Actions**:

- `--action create_epic`: `--summary`, `--description`, `--epic-actual-name`
- `--action create_task`: `--epic-name`, `--summary`, `--description`, `--issue-type`
- `--action update_issue`: `--issue-key`, `--fields` (JSON)

**Notes**: Project key "MARTIN", epic mappings auto-saved

## GitHub Integration

### Integration Strategy (Updated Nov 2025)

**PRIMARY METHOD**: Use standardized scripts that abstract gh CLI details

**DEPRECATED**: GitHub MCP server (causes 7000+ line payloads that crash Cursor on PR comment retrieval)

### PR Status Checking (STANDARD WORKFLOW)

**After pushing to PR - Use watch mode to eliminate manual checking:**

```bash
cd ${AGENT_HOME} && python3 cursor-rules/scripts/pr_status.py --watch [PR_NUMBER]
```

**Watch mode behavior:**

- Polls CI status every 30 seconds
- Shows progress updates when status changes
- **Automatically reports results when CI completes**
- No human intervention needed
- Ctrl+C to cancel

**Single status check (when CI already complete):**

```bash
cd ${AGENT_HOME} && python3 cursor-rules/scripts/pr_status.py [PR_NUMBER]
```

**What it provides:**

- PR overview (commits, lines changed, files)
- Latest commit info
- CI status (running/failed/passed)
- **Failed checks with direct links**
- In-progress checks with elapsed time
- Next steps guidance

**Exit codes:**

- `0` - All checks passed (ready to merge)
- `1` - Checks failed or in progress
- `2` - Error (no PR found, gh CLI missing)

**Workflow Integration:**

1. Make changes and commit
2. Push to PR
3. **Immediately run `--watch` mode** (no waiting for human)
4. Script polls CI automatically
5. When CI completes, results appear
6. If failures, address them immediately
7. Repeat until all green

**Benefits:**

- **Eliminates idle waiting time**
- **No manual "is CI done?" checking**
- Consistent output format
- Abstraction layer hides gh CLI complexity
- Single source of truth for PR workflow

### PR Comment Review Protocol (gh CLI)

**Step 1: Get PR number**

```bash
gh pr view --json number,title,url
```

**Step 2: Fetch PR comments and reviews**

```bash
# Get general comments and reviews
gh pr view <PR_NUMBER> --comments --json comments,reviews | jq '.'

# Get inline review comments (code-level)
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments --jq '.[] | {path: .path, line: .line, body: .body, id: .id}'
```

**Step 3: Strategic Analysis**
Group comments by underlying concept (not by file location):

- Security issues
- Export functionality
- Parsing/validation
- Test quality
- Performance

**Step 4: Address systematically**
Prioritize by risk/impact (CRITICAL > HIGH > MEDIUM > LOW)

**Step 5: Reply to comments**

```bash
# Create comment file
cat > /tmp/pr_comment.md << 'EOF'
## Response to feedback...
EOF

# Post comment
gh pr comment <PR_NUMBER> --body-file /tmp/pr_comment.md
```

### Common gh CLI Commands

**Pull Requests:**

- View PR: `gh pr view <NUMBER>`
- List PRs: `gh pr list`
- Create PR: `gh pr create --title "..." --body "..."`
- Check status: `gh pr status`

**Issues:**

- Create: `gh issue create --title "..." --body-file /tmp/issue.md`
- List: `gh issue list`
- View: `gh issue view <NUMBER>`

**Repository:**

- Clone: `gh repo clone <OWNER>/<REPO>`
- View: `gh repo view`
- Create: `gh repo create`

### Benefits of gh CLI

- Handles large payloads without crashing
- Direct JSON output with `jq` integration
- No MCP server overhead
- Reliable authentication via `gh auth login`
- Native markdown file support (`--body-file`)

## Project-Specific Rules

\_Including project rules matching:

✓ Including: slop-mop.mdc

# slop-mop

# Slop-Mop Project Rules 🧹

## Project Overview

Slop-Mop is a language-agnostic, bolt-on code validation tool designed to catch AI-generated slop before it lands in your codebase. It provides fast, actionable feedback for both human developers and AI coding assistants.

### Core Philosophy

- **Fail fast**: Stop at first failure to save time
- **Maximum value, minimum time**: Prioritize quick, high-impact checks
- **AI-friendly output**: Clear errors with exact fixes
- **Zero configuration required**: Works out of the box
- **Simple, iterative workflow**: Use profiles, fix failures one at a time

## 🚨 CRITICAL: sb IS THE ONLY TOOL 🚨

**ABSOLUTE PROHIBITION**: AI assistants MUST NOT bypass `sb` by running raw commands.

### FORBIDDEN Commands (Groundhog Day Violations)

```bash
# ❌ NEVER run these directly - they bypass sb
pytest --cov=slop-mop ...      # Use: sm validate python:coverage
pytest tests/ ...                 # Use: sm validate python:tests
black --check ...                 # Use: sm validate python:lint-format
flake8 ...                        # Use: sm validate python:lint-format
mypy ...                          # Use: sm validate python:static-analysis
bandit ...                        # Use: sm validate security:local
```

### WHY This Matters

1. **sb provides iteration guidance** - raw commands don't tell you what to do next
2. **sb respects config** - thresholds, exclusions, and settings from `.sb_config.json`
3. **sb is the product** - using raw commands means ignoring friction points we should fix
4. **Consistency** - same workflow everywhere, no context switching

### If sb Output Is Insufficient

**DO NOT work around it.** Instead:

1. Identify what information is missing from sb output
2. Update the relevant check to provide that information
3. Make sb better, don't bypass it

## AI Agent Workflow (IMPORTANT!)

**🤖 This is the intended workflow for AI coding assistants.**

### The Simple Pattern

```bash
# Just run the profile - don't overthink it!
sm validate commit
```

When a check fails, slop-mop shows you exactly what to do next:

```
┌──────────────────────────────────────────────────────────┐
│ 🤖 AI AGENT ITERATION GUIDANCE                           │
├──────────────────────────────────────────────────────────┤
│ Profile: commit                                          │
│ Failed Gate: python:coverage                             │
├──────────────────────────────────────────────────────────┤
│ NEXT STEPS:                                              │
│                                                          │
│ 1. Fix the issue described above                         │
│ 2. Validate: sm validate python:coverage                 │
│ 3. Resume:   sm validate commit                          │
│                                                          │
│ Keep iterating until all checks pass.                    │
└──────────────────────────────────────────────────────────┘
```

### What NOT to Do

```bash
# ❌ DON'T do this - verbose, misses the point of profiles
sm validate -g python:lint-format,python:static-analysis,python:tests

# ❌ DON'T do this - bypasses sb entirely (GROUNDHOG DAY VIOLATION)
pytest --cov=slop-mop --cov-report=term-missing

# ✅ DO this - simple, iterative, self-guiding
sm validate commit
```

### The Iteration Loop

1. **Run the profile**: `sm validate commit`
2. **See what fails**: Output shows exactly which gate failed
3. **Fix the issue**: Follow the guidance in the error output
4. **Validate the fix**: `sm validate <failed-gate>` (just that one gate)
5. **Resume the profile**: `sm validate commit`
6. **Repeat until green**: Keep iterating until all checks pass

### Coverage Failures - DO NOT Analyze Manually

When coverage fails:

- ❌ DON'T run `pytest --cov` to "see what's missing"
- ❌ DON'T manually calculate what tests to add
- ✅ DO read the output from `sm validate python:coverage`
- ✅ DO follow the guidance it provides
- ✅ DO improve sb's coverage output if it's not actionable enough

## CLI Commands

### Verb-Based CLI (`sb`)

```bash
# Run validation - USE PROFILES (not gate lists!)
sm validate commit                      # ← Primary workflow (fast)
sm validate pr                          # ← Before opening PR
sm validate quick                       # ← Ultra-fast lint only
sm validate python:coverage             # Validate single gate (when iterating)
sm validate --self                      # Validate slop-mop itself

# Configuration
sm config --show                        # Show current config
sm config --enable python-security      # Enable a gate
sm config --disable python-complexity   # Disable a gate

# Interactive Setup
sm init                                 # Interactive prompts
sm init --non-interactive               # Use detected defaults

# Help
sm help                                 # General help
sm help python-lint-format              # Help for specific gate
```

## Quality Gate Profiles

| Profile      | Checks Included                                         | Use Case               |
| ------------ | ------------------------------------------------------- | ---------------------- |
| `commit`     | lint-format, static-analysis, tests, coverage, security | Fast local validation  |
| `pr`         | All checks                                              | Full PR validation     |
| `quick`      | lint-format only                                        | Ultra-fast check       |
| `python`     | All Python checks                                       | Python-only validation |
| `javascript` | All JavaScript checks                                   | JS-only validation     |

## Running Tests

### ✅ CORRECT Way (Always Use sb)

```bash
sm validate python:tests               # Run tests through sb
sm validate commit                      # Run full commit profile
```

### ❌ WRONG Way (Bypasses sb)

```bash
pytest                                  # Direct pytest - NO
pytest tests/unit/test_foo.py -v       # Direct pytest - NO
pytest --cov=slop-mop                # Direct coverage - NO
```

### When You Need More Test Detail

If sb's test output doesn't give enough detail for debugging:

1. **First**: Check if sb has a `--verbose` flag
2. **If not**: Add verbose output support to the tests check
3. **Never**: Just run pytest directly as a workaround

### Test Directory Structure

```
tests/
├── conftest.py         # Shared fixtures
├── unit/               # Unit tests
│   ├── test_executor.py
│   ├── test_registry.py
│   ├── test_result.py
│   └── ...
└── integration/        # Integration tests
```

## Architecture Notes

### Check Implementation Pattern

All checks inherit from `BaseCheck`:

```python
from slop-mop.checks.base import BaseCheck
from slop-mop.core.result import CheckResult, CheckStatus
from slop-mop.core.registry import register_check

@register_check
class MyCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "my-check"

    @property
    def display_name(self) -> str:
        return "🔧 My Custom Check"

    def is_applicable(self, project_root: str) -> bool:
        return True  # Check for specific files/conditions

    def run(self, project_root: str) -> CheckResult:
        # Check logic here
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            duration=0.1,
            output="Check passed!"
        )
```

### Key Modules

| Module                             | Purpose                          |
| ---------------------------------- | -------------------------------- |
| `slop-mop/sb.py`                   | CLI entry point (verb-based)     |
| `slop-mop/core/executor.py`        | Parallel check execution         |
| `slop-mop/core/registry.py`        | Check registration and discovery |
| `slop-mop/core/result.py`          | Result types and status          |
| `slop-mop/subprocess/runner.py`    | Secure subprocess execution      |
| `slop-mop/subprocess/validator.py` | Command whitelist validation     |
| `slop-mop/checks/`                 | Check implementations            |
| `slop-mop/reporting/console.py`    | Output formatting                |

### Security Model

Slop-Mop uses a whitelist-based security model for subprocess execution:

- Only known, safe executables can be run (python, npm, black, etc.)
- No `shell=True` execution
- All arguments validated for injection patterns
- Custom executables can be added via configuration

## Development Workflow

### Self-Validation (Dogfooding)

Always run slop-mop on itself before committing:

```bash
# Quick check
sm validate --self commit

# Full PR check
sm validate --self pr
```

### Adding New Checks

1. Create check file in appropriate directory (`checks/python/`, `checks/javascript/`, etc.)
2. Implement `BaseCheck` interface
3. Use `@register_check` decorator
4. Add tests in `tests/unit/`
5. Update aliases in registry if needed

### Improving sb When It's Not Enough

**This is critical**: When sb output doesn't give you what you need, FIX SB.

Examples:

- Coverage check doesn't show which files need tests? → Update coverage.py to show top uncovered files
- Test failures don't show enough context? → Add verbose flag to tests check
- Security check flags something you can't understand? → Improve the error message

**Anti-pattern**: Running raw `pytest --cov` to "get more info" - this is a workaround that ignores the real problem (sb's output isn't good enough).

## Configuration

### .sb_config.json Structure

```json
{
  "version": "1.0",
  "default_profile": "commit",
  "python": {
    "enabled": true,
    "include_dirs": ["slop-mop"],
    "gates": {
      "lint-format": { "enabled": true },
      "tests": { "enabled": true, "test_dirs": ["tests"] },
      "coverage": { "enabled": true, "threshold": 80 }
    }
  }
}
```

### Adjusting Thresholds

If a threshold is wrong, update `.sb_config.json`:

```bash
# View current config
sm config --show

# Edit .sb_config.json directly for threshold changes
```

## Common Issues

### "Coverage Below Threshold"

- Read the sb output - it tells you what to do
- DO NOT run `pytest --cov` manually
- If sb's guidance isn't clear, improve the coverage check output

### "No checks registered" Error

Run `sm init` to set up the project.

### Subprocess Security Errors

Add the executable to the validator's allowed list in `slop-mop/subprocess/validator.py`.

## PR Review Notes

This project has an open PR (#1) implementing the core quality gate framework. Key areas to focus on during review:

- Check execution flow and error handling
- Security of subprocess execution
- Test coverage adequacy
- CLI usability and error messages

---

## About This File

This `AGENTS.md` file follows the emerging open standard for AI agent instructions.
It is automatically generated from modular rule files in `cursor-rules/.cursor/rules/`.

**Supported AI Tools:**

- Cursor IDE (also reads `.cursor/rules/*.mdc` directly)
- Antigravity (Google Deepmind)
- Cline (VS Code extension)
- Roo Code (VS Code extension)
- Other AI coding assistants that support AGENTS.md

**Also available:** This same content is provided in `.windsurfrules` for Windsurf IDE compatibility.
