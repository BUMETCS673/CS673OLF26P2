# Cadence

An AI-assisted spaced-repetition learning platform. Describe what you want to learn, and Cadence writes the flashcards, then schedules them so you review each one right before you'd forget it.

<!-- Badges go here once CI is configured in Iteration 2:
[![CI](https://github.com/BUMETCS673/CS673OLF26P2/actions/workflows/ci.yml/badge.svg)](...)
[![Coverage](...)](...)
-->

<!-- Screenshot or demo GIF goes here once the review interface exists -->

## Why

Spaced repetition works, but the tools built around it ask a lot of the learner. Building a deck in Anki means writing every card by hand or hunting down someone else's deck that doesn't quite fit. And the default review format — reveal the answer, grade yourself — suits some material poorly and leaves honest assessment up to you.

Cadence generates cards from a prompt or your own source material, then drills them through several interaction formats with assisted grading. The scheduling model follows Anki's, which is well-proven; the authoring and review experience is where we differ.

It's aimed at people who need to retain a lot of discrete facts: students in medicine, law, and the sciences, language learners, and anyone studying for a certification exam.

## Features

- **AI deck generation** — supply a topic prompt or source material and review the cards the model proposes, accepting, editing, or discarding each one
- **Deck management** — create, organize, edit, and delete decks and cards at any time
- **Spaced repetition scheduling** — per-card performance tracking that schedules each review at the interval where reinforcement is most valuable
- **Multiple review formats** — reveal-and-grade recall, free-text entry, and multiple choice
- **Persistent history** — decks, cards, and study progress survive across sessions

## Tech Stack

React · Python · PostgreSQL · Docker · GitHub Actions

> Provisional. Final selections are confirmed in Iteration 1 design.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- _Node and Python versions TBD_

### Setup

```bash
git clone https://github.com/BUMETCS673/CS673OLF26P2.git
cd CS673OLF26P2
cp .env.example .env   # add your LLM API key
docker compose up
```

_Full setup, environment variables, and run instructions land here in Iteration 1 once the project skeleton exists._

### Tests

```bash
# TBD
```

## Repository Structure

```
docs/     Project documentation — SPPP, SDD, STD, meeting minutes,
          progress reports, iteration presentations
code/
  frontend/   React client
  backend/    Python API service
```

## Contributing

Branching model, commit conventions, PR requirements, and the AI attribution format are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

_TBD._ If we build on Anki's codebase, its AGPL-3.0 terms apply to our work; if we implement scheduling independently, we're free to choose. Decision to be made in Iteration 1 design.

---

<sub>Built for CS673 Software Engineering, Boston University Metropolitan College, Fall 1 2026 — Team 2: Miles (team lead), Nurzat (requirements), Paul (frontend), Victor (backend), Duc (config/DevOps), Osasenaga (QA).</sub>
