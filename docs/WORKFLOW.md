# Slop-Mop Workflow

> **Auto-generated** — do not edit by hand.
> Source of truth: `slopmop/workflow/state_machine.py`
> Re-generate: `python scripts/gen_workflow_diagrams.py`

The slop-mop development loop is a small state machine.  Every tool
invocation advances the machine; the terminal `walk-forward` gate in
`sm scour` always tells you the next step.

---

## Relationship diagram

```mermaid
stateDiagram-v2
    direction LR
    coding : During implementation
    swab_clean : Swab passed
    buff_iterating : Addressing feedback
    committed : Changes committed
    scour_clean : Scour passed
    pr_open : PR open — awaiting CI/review
    pr_ready : PR ready to land

    coding --> swab_clean : passes
    coding --> coding : fails
    buff_iterating --> swab_clean : passes
    buff_iterating --> buff_iterating : fails
    swab_clean --> committed : committed
    committed --> scour_clean : passes
    committed --> coding : fails
    scour_clean --> pr_open : PR opened/updated
    pr_open --> buff_iterating : has issues
    pr_open --> pr_ready : all green
    buff_iterating --> coding : iteration prepared
    pr_ready --> pr_open : final push
```

---

## Developer timeline

```mermaid
flowchart TD
    START["During implementation"]
    SWAB["Run sm swab"]
    COMMIT["Commit"]
    BEFORE_PR["Before PR update/open"]
    SCOUR["Run sm scour"]
    OPEN_PR["Open/update PR"]
    AFTER_PR["After PR opens / CI feedback"]
    BUFF["Run sm buff"]
    FIX["Fix findings"]

    START --> SWAB
    SWAB -->|"passes"| COMMIT
    SWAB -->|"fails"| FIX
    COMMIT --> BEFORE_PR
    BEFORE_PR --> SCOUR
    SCOUR -->|"passes"| OPEN_PR
    SCOUR -->|"fails"| FIX
    OPEN_PR --> AFTER_PR
    AFTER_PR --> BUFF
    BUFF -->|"actionable guidance"| FIX
    FIX --> SWAB
```

---

## States

| State | Meaning | Docstring |
|---|---|---|
| `coding` | During implementation | Every possible position in the development loop. |
| `swab_clean` | Swab passed | Every possible position in the development loop. |
| `buff_iterating` | Addressing feedback | Every possible position in the development loop. |
| `committed` | Changes committed | Every possible position in the development loop. |
| `scour_clean` | Scour passed | Every possible position in the development loop. |
| `pr_open` | PR open — awaiting CI/review | Every possible position in the development loop. |
| `pr_ready` | PR ready to land | Every possible position in the development loop. |

---

## Transitions

| From state | Event | To state | Next action |
|---|---|---|---|
| `coding` | `swab\_passed` | `swab\_clean` | git commit your changes |
| `coding` | `swab\_failed` | `coding` | fix the reported findings, re-run sm swab |
| `buff\_iterating` | `swab\_passed` | `swab\_clean` | git commit your changes |
| `buff\_iterating` | `swab\_failed` | `buff\_iterating` | fix the reported findings, re-run sm swab |
| `swab\_clean` | `git\_committed` | `committed` | sm scour |
| `committed` | `scour\_passed` | `scour\_clean` | git push && open or update PR |
| `committed` | `scour\_failed` | `coding` | fix the reported findings, re-run sm swab |
| `scour\_clean` | `pr\_opened` | `pr\_open` | sm buff inspect |
| `pr\_open` | `buff\_has\_issues` | `buff\_iterating` | sm buff iterate — then fix findings and run sm swab |
| `pr\_open` | `buff\_all\_green` | `pr\_ready` | sm buff finalize --push |
| `buff\_iterating` | `iteration\_started` | `coding` | fix findings, then run sm swab |
| `pr\_ready` | `pr\_opened` | `pr\_open` | sm buff inspect |
