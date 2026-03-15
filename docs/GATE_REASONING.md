# Gate Reasoning

This file is generated from built-in gate metadata. Edit the gate reasoning source of truth in `slopmop/checks/metadata.py`, then regenerate it.

## 🔴 Overconfidence

### `overconfidence:coverage-gaps.dart`

- Rationale: If changed Dart code can land without tests proving it, coverage turns decorative and the hole just moves around the repo.
- Tradeoffs: Coverage work slows down spikes and sometimes forces harness cleanup before the feature feels done.
- Override When: Bend this for short-lived spikes, active incidents, or other explicitly time-critical work with agreement that the coverage debt gets paid back.

### `overconfidence:coverage-gaps.js`

- Rationale: If changed JavaScript code can land without tests proving it, coverage turns decorative and the hole just moves around the repo.
- Tradeoffs: Coverage work slows down spikes and sometimes forces harness cleanup before the feature feels done.
- Override When: Bend this for short-lived spikes, active incidents, or other explicitly time-critical work with agreement that the coverage debt gets paid back.

### `overconfidence:coverage-gaps.py`

- Rationale: If changed Python code can land without tests proving it, coverage turns decorative and the hole just moves around the repo.
- Tradeoffs: Coverage work slows down spikes and sometimes forces harness cleanup before the feature feels done.
- Override When: Bend this for short-lived spikes, active incidents, or other explicitly time-critical work with agreement that the coverage debt gets paid back.

### `overconfidence:missing-annotations.dart`

- Rationale: Missing Dart annotations turn interfaces into vibes and push type noise downstream for somebody else to untangle.
- Tradeoffs: Adding annotations can expose a bigger cleanup than the line that first tripped the gate.
- Override When: Bend this for short spikes or throwaway glue code, not for stable surfaces other code is going to lean on.

### `overconfidence:missing-annotations.py`

- Rationale: Missing Python annotations turn interfaces into vibes and push type noise downstream for somebody else to untangle.
- Tradeoffs: Adding annotations can expose a bigger cleanup than the line that first tripped the gate.
- Override When: Bend this for short spikes or throwaway glue code, not for stable surfaces other code is going to lean on.

### `overconfidence:type-blindness.js`

- Rationale: If the type checker cannot tell what something is in TypeScript, humans and agents are left guessing too.
- Tradeoffs: Strict typing often drags surrounding ambiguity into the light, so the fix can widen before it narrows.
- Override When: Bend this for spikes or incident work where you are explicitly buying short-term ambiguity to move faster.

### `overconfidence:type-blindness.py`

- Rationale: If the type checker cannot tell what something is in Python, humans and agents are left guessing too.
- Tradeoffs: Strict typing often drags surrounding ambiguity into the light, so the fix can widen before it narrows.
- Override When: Bend this for spikes or incident work where you are explicitly buying short-term ambiguity to move faster.

### `overconfidence:untested-code.dart`

- Rationale: Passing compilation is not proof; if Dart code never executes under test, you are still guessing.
- Tradeoffs: Full test runs cost real time, especially in slower suites or flaky legacy harnesses.
- Override When: Use discretion during incident response or truly throwaway spikes where fast feedback matters more than full proof.

### `overconfidence:untested-code.js`

- Rationale: Passing compilation is not proof; if JavaScript code never executes under test, you are still guessing.
- Tradeoffs: Full test runs cost real time, especially in slower suites or flaky legacy harnesses.
- Override When: Use discretion during incident response or truly throwaway spikes where fast feedback matters more than full proof.

### `overconfidence:untested-code.py`

- Rationale: Passing compilation is not proof; if Python code never executes under test, you are still guessing.
- Tradeoffs: Full test runs cost real time, especially in slower suites or flaky legacy harnesses.
- Override When: Use discretion during incident response or truly throwaway spikes where fast feedback matters more than full proof.

## 🟡 Deceptiveness

### `deceptiveness:bogus-tests.dart`

- Rationale: A fake Dart test suite is worse than no test suite because it teaches people to trust green lies.
- Tradeoffs: The strict version can be annoying when you sketch a test first and plan to fill the assertions in a minute later.
- Override When: Fine to relax briefly in draft-only local work, not in committed code that is pretending to be review-ready.

### `deceptiveness:bogus-tests.js`

- Rationale: A fake JavaScript test suite is worse than no test suite because it teaches people to trust green lies.
- Tradeoffs: The strict version can be annoying when you sketch a test first and plan to fill the assertions in a minute later.
- Override When: Fine to relax briefly in draft-only local work, not in committed code that is pretending to be review-ready.

### `deceptiveness:bogus-tests.py`

- Rationale: A fake Python test suite is worse than no test suite because it teaches people to trust green lies.
- Tradeoffs: The strict version can be annoying when you sketch a test first and plan to fill the assertions in a minute later.
- Override When: Fine to relax briefly in draft-only local work, not in committed code that is pretending to be review-ready.

### `deceptiveness:debugger-artifacts`

- Rationale: Leftover breakpoints are the kind of tiny accident that can wreck a real run in embarrassingly expensive ways.
- Tradeoffs: The only real cost is a little friction when you are actively debugging and want quick iteration.
- Override When: Fine in local scratch work; not fine once the change is headed toward a commit or a PR.

### `deceptiveness:gate-dodging`

- Rationale: If the fix is 'turn the smoke alarm down,' the repo learns the wrong lesson and the next regression walks right in.
- Tradeoffs: Sometimes legit threshold tuning is necessary, and this gate makes you prove the difference instead of waving at it.
- Override When: Override only when the threshold itself is wrong and you are intentionally recalibrating policy, not when the current diff is just inconvenient.

### `deceptiveness:hand-wavy-tests.js`

- Rationale: If JavaScript tests never assert, the suite is just theater with npm around it.
- Tradeoffs: Assertion-enforcement can be noisy while a test is half-written or when a framework hides assertions behind helpers.
- Override When: Bend this only for draft local work or framework edge cases you have explicitly accounted for.

## 🟠 Laziness

### `laziness:broken-templates.py`

- Rationale: Template bugs like to wait until a user path hits them, which is a lousy time to discover syntax errors.
- Tradeoffs: Template validation can be noisy in repos with partials or unconventional render-context setup.
- Override When: Relax it only for prototypes or repos where the template is not actually part of the shipped path yet.

### `laziness:complexity-creep.py`

- Rationale: Big branching functions are where edge cases go to hide and future fixes go to die.
- Tradeoffs: Refactors to reduce complexity can be broader and riskier than the immediate bug fix that triggered the work.
- Override When: Bend this during incident stabilization, then come back and split the function once the fire is out.

### `laziness:dead-code.py`

- Rationale: Dead code makes the map lie. People read paths that do not matter and miss the ones that do.
- Tradeoffs: Static dead-code tools can false-positive on dynamic hooks, plugins, and intentionally indirect entrypoints.
- Override When: Override for known dynamic entrypoints with a concrete explanation, not because the deletion is inconvenient right now.

### `laziness:generated-artifacts.dart`

- Rationale: Checking in generated junk is how you turn diffs into static and invite edits that get wiped later.
- Tradeoffs: Sometimes the generated output is the artifact you actually need to ship or preserve as a fixture.
- Override When: Allow it when the generated file is intentionally versioned, not when it is just local build fallout hitching a ride.

### `laziness:silenced-gates`

- Rationale: A disabled gate is usually debt with a welcome mat on it.
- Tradeoffs: Sometimes a gate really is wrong for the repo or temporarily broken by external churn.
- Override When: Override only when disabling is an explicit policy choice with a tracked reason, not as a drive-by escape hatch.

### `laziness:sloppy-formatting.dart`

- Rationale: Formatting noise hides the real change and makes review slower than it needs to be.
- Tradeoffs: It can feel like busywork when you are in the middle of a real fix and the code already runs.
- Override When: Relax it briefly for throwaway spikes or incident patches, not for normal feature work headed to review.

### `laziness:sloppy-formatting.js`

- Rationale: Formatting noise hides the real change and makes review slower than it needs to be.
- Tradeoffs: It can feel like busywork when you are in the middle of a real fix and the code already runs.
- Override When: Relax it briefly for throwaway spikes or incident patches, not for normal feature work headed to review.

### `laziness:sloppy-formatting.py`

- Rationale: Formatting noise hides the real change and makes review slower than it needs to be.
- Tradeoffs: It can feel like busywork when you are in the middle of a real fix and the code already runs.
- Override When: Relax it briefly for throwaway spikes or incident patches, not for normal feature work headed to review.

### `laziness:sloppy-frontend.js`

- Rationale: Frontend lint issues have a habit of turning into visible bugs, state leaks, or accessibility damage.
- Tradeoffs: Quick lint passes can bark at work-in-progress code while a larger refactor is still mid-flight.
- Override When: Relax it briefly during spikes or refactors in motion, not for settled code headed to review.

## 🔵 Myopia

### `myopia:code-sprawl`

- Rationale: Once files and functions get too big, nobody can safely reason about them in one pass, including the model.
- Tradeoffs: Splitting code takes time and can feel like ceremony while you are still exploring the shape of the solution.
- Override When: Bend this for short spikes while the design is still liquid, then pay the split tax before the code hardens.

### `myopia:dependency-risk.py`

- Rationale: Your code can be clean and still ship someone else's CVE to production.
- Tradeoffs: Dependency audits can produce noisy or low-signal findings, especially when advisories lag behind reality.
- Override When: Temporarily waive only with a conscious risk call, usually during incident work or when the upstream fix path is outside your control.

### `myopia:ignored-feedback`

- Rationale: Unresolved review threads turn the PR loop into Groundhog Day and hide known concerns in plain sight.
- Tradeoffs: Sometimes a thread is stale, blocked on reviewer input, or attached to code that has changed shape since the comment landed.
- Override When: Override only when you have explicitly resolved the thread state with evidence or you are waiting on human clarification.

### `myopia:just-this-once.py`

- Rationale: If changed lines can land untested, overall coverage becomes a nice story the PR does not actually obey.
- Tradeoffs: Diff coverage can be painful on legacy code where touching one line exposes a whole untested neighborhood.
- Override When: Bend this for spikes, emergency patches, or intentionally exploratory diffs with an agreed follow-up to close the gap.

### `myopia:source-duplication`

- Rationale: Copy-pasted logic diverges in slow motion until every bug fix becomes a scavenger hunt.
- Tradeoffs: Deduping too early can create the wrong abstraction and make simple code feel clever for no reason.
- Override When: Hold off when the repeated code is still genuinely in discovery mode and the shared shape is not stable yet.

### `myopia:string-duplication.py`

- Rationale: Repeated literals hide shared rules and make the repo drift by typo instead of design.
- Tradeoffs: Not every repeated string deserves an abstraction, and the gate can tempt people into inventing constants nobody needed.
- Override When: Override for truly incidental repeats like local test data or tiny messages that are not carrying shared business meaning.

### `myopia:vulnerability-blindness.py`

- Rationale: Code can pass tests and types and still be an own-goal from a security perspective.
- Tradeoffs: Security scanners throw false positives and sometimes demand context they cannot infer from static analysis.
- Override When: Waive only with a specific risk decision and rationale, not because the scanner is inconvenient.
