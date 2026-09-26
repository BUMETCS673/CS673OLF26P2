# Cadence — Lab 3 User Stories

Drafts for the Jira board: one story for each user story in [LAB_3_PLAN.md](LAB_3_PLAN.md).
Steps 0a and 0b aren't here. They're setup chores with nothing a learner would notice, so if we
track them on the board at all, they go in as tasks.

Each story follows the template that graded well: the user story, its business value, and
Given / When / Then acceptance tests with concrete values. The acceptance tests describe what the
learner experiences. The plan has the matching technical test lists.

## Putting these on the board

Each story starts with a `<!-- jira ... -->` line, which GitHub doesn't display. It holds the
story's labels, a story-point estimate (5 is about a day of work, 3 about half a day), and which
story in the plan it implements. The `##` heading becomes the Jira summary, and everything under
it, down to the next story, becomes the description.

The script below is written for [jira-cli](https://github.com/ankitpokhrel/jira-cli), the `jira`
command. Run `jira init` once to connect it to our board. By default the script only prints the
commands it would run; check them, then run it again with `RUN=1` in front to create the issues.

```bash
cd code/plans
python3 - <<'EOF'
import os, pathlib, re, shlex, subprocess, tempfile

text = pathlib.Path("LAB_3_USER_STORIES.md").read_text()
stories = re.findall(r"<!-- jira (.*?) -->\n## (.+?)\n(.*?)(?=\n<!-- jira |\Z)", text, re.S)
for attrs, summary, body in stories:
    meta = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
    body = body.strip().removesuffix("---").strip()
    body += f"\n\nImplementation: code/plans/LAB_3_PLAN.md, {meta['plan']}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
    cmd = ["jira", "issue", "create", "-t", "Story", "-s", summary,
           "--template", f.name, "--no-input"]
    for label in meta["labels"].split(","):
        cmd += ["-l", label]
    if os.environ.get("EPIC"):
        cmd += ["-P", os.environ["EPIC"]]
    if os.environ.get("POINTS_FIELD"):
        cmd += ["--custom", f"{os.environ['POINTS_FIELD']}={meta['points']}"]
    print(shlex.join(cmd))
    if os.environ.get("RUN") == "1":
        subprocess.run(cmd, check=True)
        os.unlink(f.name)
EOF
```

Optional settings, placed in front of `python3` like `RUN=1`:

- `EPIC=<issue key>` attaches every story to an epic, such as a "Study mode" epic.
- `POINTS_FIELD=<name>` sets story points, where `<name>` is the story-points field's name in
  jira-cli's config.

The script also adds a line to each description that links back to the story in the plan. In
the default print-only mode it leaves each description in a temp file, at the path shown after
`--template`, so you can read exactly what will be sent.

---

<!-- jira labels="lab-3,iteration-2,study-mode,backend" points="5" plan="Story 1" -->
## Schedule each card's next review from my rating

As a learner working through a deck, I want each card's next review scheduled from how well I
recalled it, so that I see the cards I struggle with often and the ones I know well only rarely.

### Business Value

Spaced repetition is the core promise of Cadence: showing each card just before the learner would
forget it is what makes study time efficient. Rather than invent our own rules, we use Anki's
default scheduling algorithm, which is well proven and behaves the way long-time Anki users
expect. Every other study feature depends on these rules being right, so each one is pinned down
with exact expected intervals.

### Acceptance Tests

**Acceptance Test 1 — A new card starts with short learning steps**

Given the learner has a card they have never studied,

When the learner rates it Good,

Then the platform should schedule the card to come back in 10 minutes.

**Acceptance Test 2 — A card graduates after its learning steps**

Given a card the learner rated Good 10 minutes ago, now back for its second learning step,

When the learner rates it Good again,

Then the platform should schedule the card's first full review for 1 day later.

**Acceptance Test 3 — Recalling a known card stretches its interval**

Given a card with a 10-day interval and the default 250% ease that is due today,

When the learner rates it Good,

Then the platform should schedule its next review 25 days later.

**Acceptance Test 4 — A late review earns extra credit**

Given the same card with a 10-day interval, reviewed 4 days after it was due,

When the learner rates it Good,

Then the platform should schedule its next review 30 days later.

**Acceptance Test 5 — Forgetting a card sends it back to relearning**

Given a card with a 30-day interval and 250% ease,

When the learner rates it Again,

Then the platform should show the card again in 10 minutes, lower its ease to 230%, and reset its
interval so that it returns 1 day after the learner relearns it.

---

<!-- jira labels="lab-3,iteration-2,study-mode,backend" points="3" plan="Story 2" -->
## Study only the cards that are due

As a learner opening a deck to study, I want to be given only the cards that are due now, so that
I don't waste time re-studying cards I just learned or face every new card at once.

### Business Value

Reviewing a card before it's due wastes effort and weakens the spacing that makes review work,
while a session holding every new card at once overwhelms learners, especially once AI generation
can add dozens of cards to a deck in one step. Serving exactly the due cards, most overdue first,
with a cap of 20 new cards per session, keeps each session focused and a manageable size.

### Acceptance Tests

**Acceptance Test 1 — Only due reviews are served, most overdue first**

Given the learner's deck has review cards that were due 3 days ago, due yesterday, and due
tomorrow,

When the learner starts studying the deck,

Then the platform should serve the card due 3 days ago first, then the card due yesterday, and
should not serve the card due tomorrow.

**Acceptance Test 2 — New cards are capped per session**

Given the learner's deck contains 25 cards they have never studied,

When the learner starts studying the deck,

Then the platform should serve the 20 cards that were added first and hold the remaining 5 for a
later session.

**Acceptance Test 3 — Cards in learning come back when they're nearly due**

Given the learner's deck has one learning card due in 5 minutes and another due in 30 minutes,

When the learner starts studying the deck,

Then the platform should include the card due in 5 minutes and hold back the card due in 30
minutes.

**Acceptance Test 4 — Another learner's deck stays private**

Given a deck that belongs to a different learner,

When the learner asks to study it,

Then the platform should respond as though the deck does not exist and reveal none of its cards.

---

<!-- jira labels="lab-3,iteration-2,study-mode,frontend" points="5" plan="Story 3" -->
## Study a deck one card at a time

As a learner in a study session, I want to see one card at a time, reveal the answer when I'm
ready, and rate how well I knew it, so that I practice recalling each answer instead of just
reading it.

### Business Value

Trying to recall an answer before seeing it is what makes flashcard study effective (Roediger &
Karpicke, 2006, cited in our SPPP). A session that hides each answer until the learner asks for
it, takes their rating, and brings cards still being learned back at the right moment is the core
study experience, and the part of Cadence where learners will spend most of their time.

### Acceptance Tests

**Acceptance Test 1 — The answer stays hidden until revealed**

Given a study session with one review card and two new cards,

When the session starts,

Then the platform should show the front of the review card with its answer hidden, and should not
accept a rating until the learner reveals the answer.

**Acceptance Test 2 — Cards still being learned come back when they're due**

Given the learner has just rated a new card Good, the card is due again in 10 minutes, and other
cards remain in the session,

When the learner continues studying,

Then the platform should move on to the next remaining card, and show the learning card again once
its 10 minutes have passed.

**Acceptance Test 3 — The same card never appears twice in a row**

Given only two learning cards, A and B, remain in the session,

When the learner rates card A Again,

Then the platform should show card B next instead of repeating card A immediately.

**Acceptance Test 4 — The session ends with a summary**

Given the learner is on the last card of the session, and one learning card is due again in 25
minutes,

When the learner rates the last card,

Then the platform should end the session, show how many cards received each rating, and tell the
learner that more cards will be due in 25 minutes.

---

<!-- jira labels="lab-3,iteration-2,study-mode,frontend" points="3" plan="Story 4" -->
## Check my typed answer

As a learner who wants to test exact recall, I want to type my answer and have the platform check
it, so that I get an honest assessment instead of grading myself.

### Business Value

Self-grading puts the burden of honest assessment on the learner and suits some material poorly,
which is one of the two Anki limitations Cadence set out to address. Checking a typed answer,
while forgiving capitalization, stray punctuation, and small typos, gives learners an objective
signal and a suggested rating. They can still overrule it when they typed a valid synonym.

### Acceptance Tests

**Acceptance Test 1 — Formatting differences don't count against the learner**

Given a card whose answer is "the library",

When the learner types "The Library.",

Then the platform should mark the answer correct and suggest the rating Good.

**Acceptance Test 2 — A small typo counts as close**

Given a card whose answer is "la biblioteca",

When the learner types "la bibloteca",

Then the platform should mark the answer close and suggest the rating Hard.

**Acceptance Test 3 — A missing accent counts as close**

Given a card whose answer is "adiós",

When the learner types "adios",

Then the platform should mark the answer close and suggest the rating Hard.

**Acceptance Test 4 — Numbers must match exactly**

Given a card whose answer is "1945",

When the learner types "1946",

Then the platform should mark the answer incorrect and suggest the rating Again.

---

<!-- jira labels="lab-3,iteration-2,study-mode,backend" points="3" plan="Story 5" -->
## Save my rating after each card

As a learner who has just rated a card, I want my rating saved right away, so that the platform
remembers when to show me that card next, even if I leave in the middle of a session.

### Business Value

Spaced repetition only works if the platform remembers every rating; without that, each session
would start from scratch. Saving each rating the moment it's given, rather than at the end of the
session, means an interrupted session loses nothing. Refusing a second rating for a card that
isn't due yet protects the learner's schedule from an accidental double-click.

### Acceptance Tests

**Acceptance Test 1 — A rating is saved immediately**

Given a card the learner has never studied,

When the learner rates it Good,

Then the platform should save the card as due again in 10 minutes, and still show that due time
after the learner reloads the deck.

**Acceptance Test 2 — A card can't be rated again before it's due**

Given the learner has just rated a card with a 10-day interval Good, so it is next due in 25 days,

When a second Good rating arrives for the same card, such as from a double-click,

Then the platform should refuse the second rating and keep the card due in 25 days.

**Acceptance Test 3 — Only the four ratings are accepted**

Given a card that is due for review,

When a rating other than Again, Hard, Good, or Easy is submitted,

Then the platform should reject it with a message saying the rating is invalid, and leave the card
unchanged.

**Acceptance Test 4 — Another learner's card can't be rated**

Given a card in a deck that belongs to a different learner,

When the learner tries to rate it,

Then the platform should respond as though the card does not exist, and leave the card unchanged.
