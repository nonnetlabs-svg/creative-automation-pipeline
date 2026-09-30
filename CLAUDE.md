# Rules for this repo
Review mode: AI writes, I review. Every change must be small, explained, and within spec.

- One module per turn, ~80–120 lines: small enough to review, but never split a change
  mid-thought just to hit a number.
- Explain each decision in 3 sentences max before coding.
- Follow the design docs in /docs. Don't add features not in them.
- Flag real tradeoffs vs conventions.
- After each module, ask a check question: I don't merge code I can't explain.
- Never read, print, or log the contents of .env.
- Principle: real-world data shapes, fake infrastructure. No integrations beyond /docs.