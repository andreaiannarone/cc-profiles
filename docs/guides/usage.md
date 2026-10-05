# Usage

The **Usage** tab (`g u`) shows how many tokens Claude used in each profile, per day, per project and per model, with an estimated cost. It is read-only: it reads the conversations Claude Code saved and changes nothing.

## Pick what to see

- **Profile**: *All profiles* or one of them. With *All profiles* a table at the bottom splits the totals by profile.
- **Period**: the last 7, 30, 90 or 365 days, today included, in your computer's time zone.

## What it shows

| Part | What it counts |
|---|---|
| **Tokens** | input + output + cache write + cache read, with how many went in and came out |
| **Estimated cost** | the tokens at Anthropic's list prices (see below) |
| **Replies** | the replies Claude wrote, and in how many projects |
| **Cache read share** | the part of the input tokens served from the prompt cache. A high share is normal for Claude Code and keeps costs down |
| **Tokens per day** | one bar per day, every day of the period (empty days included), split into output, input and cache write, and cache read. Hover a bar to read its numbers |
| **Top projects** | the 10 projects with the most tokens, with their profile |
| **Models** | each model's replies and tokens by kind, and its cost |

## Where the numbers come from

Claude Code records the token usage of every reply in the conversation files, `projects/<name>/<session>.jsonl` (and `<session>/subagents/*.jsonl` for subagents). cc-profiles adds them up:

- A reply written over several lines, or copied into a resumed conversation, counts once (same message id and request id). With *All profiles*, a reply present in two profiles counts once too.
- Lines that cannot be read are skipped.
- A conversation you deleted or that Claude Code cleaned up (`cleanupPeriodDays`) is no longer counted.

Each file is read once and kept in memory until it changes, so the tab stays fast on large homes; nothing is written to disk.

## About the cost

The cost is an **estimate at list price**, from a small table of prices per model family (Opus, Sonnet, Haiku and their generations), in USD per million tokens, kept in `src/cc_profiles/usage.py` with the date it was checked. Cache writes are priced as 5-minute writes (1.25 × input), or 2 × input when Claude Code reports them as 1-hour writes.

- **Subscription plans (Pro, Max, Team) are not billed per token.** For them the number says what the same use would have cost through the API, not what you pay.
- API usage through Amazon Bedrock, Google Vertex AI or other providers has its own prices.
- Models without a list price in the table (for example `<synthetic>` lines) count their tokens but no cost; the totals then carry a `*`.
