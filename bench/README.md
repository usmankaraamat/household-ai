# What the home model can and can't do

Measured on 26 Sep 2026, on an RTX 3060 Ti (8 GB, CUDA) under Windows, with Ollama 0.34.4.
The family's Mac mini has 16–64 GB of unified memory and runs Metal, so **the speed numbers
won't carry over**. The method, and how quality changes with model and context size, will.
On day one, the same two commands run on their machine:

    python -m bench.run        # accuracy: 21 questions over the sample documents
    python -m bench.context    # usable context: a hidden sentence in 4K–32K of text

Saved answers can be scored again under new rules without running a model:

    python -m bench.run --rescore bench/results/accuracy-2026-09-26-1943.json

Models: Granite 4.2 8B and Qwen3.5 9B, both off-the-shelf Q4_K_M GGUF. The Qwen build is
the text-only one from unsloth: Ollama's own `qwen3.5:9b` bundles a 0.86 GB image model that
would take up VRAM and do nothing here. Thinking is switched off for both (see below).

## Accuracy — [results](results/accuracy-latest.md)

| | Granite 4.2 8B | Qwen3.5 9B |
|---|---|---|
| Correct | 20/21 | 19/21 |
| One-document facts | 13/13 | 13/13 |
| Answers that combine two documents | 3/4 | 2/4 |
| Says "not found" instead of guessing | 3/3 | 3/3 |
| Cites a document search didn't return | 0 | 0 |
| Reasoning leaked into the answer | 1 | 0 |
| Median time per answer | 3.4 s | 3.4 s |

**How an answer is scored.** It must contain every required fact, must not contain a value
known to be wrong for that question, and a refusal must be exactly `NOT FOUND`: "NOT FOUND,
but probably $500" counts as a guess. Citations are checked against what search actually
returned. The first version of the scorer only looked for keywords and reported Granite at
21/21; these numbers are the same saved answers re-scored under the stricter rules.

**How much to read into it.** 21 questions, and only 4 that combine two documents, can show
where a model breaks, but not a reliable difference between two models. Treat 20 vs 19 as a
tie, and 3/4 vs 2/4 as a hint to test more two-document questions on the Mac mini.

Search found every needed document for every question, so each miss is the model's own.
The misses that matter:

- **Qwen, "the AC stopped working, who do we call?"** It knew the lease makes repairs the
  landlord's job, then gave the HVAC company's number, not the landlord's emergency line.
- **Qwen, "what time does Rosa start on Wednesdays?"** It quoted "45 minutes before
  dismissal" and then answered 1:30, the dismissal time itself.
- **Granite, "is the filter overdue?"** Right answer, wrong detail: it said the change was
  due 4 September when 90 days from 3 June is 1 September. The keyword scorer passed it; the
  question now lists that date as wrong, so it fails. Small models get simple date arithmetic
  wrong, so anything with a deadline should show its source.
- **Granite, "who do I call for a tow?"** The answer was right, but its reasoning leaked into
  the reply even with thinking switched off: a closing `</think>` with no opening tag, which
  the old clean-up missed. The family would have seen the model thinking out loud, including
  document names it considered and didn't use. Everything before a stray `</think>` is now
  removed, and the benchmark counts it.

Neither model invented an answer to the three questions the documents can't answer,
including "our renters insurance deductible", where two other deductibles are nearby.

## Usable context — [results](results/context-latest.md)

| Context | Granite: tok/s, on GPU | Qwen: tok/s, on GPU |
|---|---|---|
| 4K | 64, 100% | 67, 100% |
| 8K | 31, 92% | 55, 88% |
| 16K | 6, 76% | 38, 84% |
| 32K | 1.7, 56% | 16, 76% |

Both found the hidden sentence at every size and position. What limits them is speed.
Granite's memory for context grows from 5.9 GB to 11 GB between 4K and 32K, spills off the
card, and slows by about 40 times. Qwen's grows from 5.6 to 7.4 GB.

## What this means for the house

- **Use a different model for each job.** Document questions send about 600 tokens of
  retrieved text, where both models do well and Granite was slightly ahead on two-document
  questions (a hint, on 4 questions, not a result). Meeting summaries send the
  whole transcript: a 30–60 minute meeting is 7–15K tokens, where Qwen stays usable and
  Granite doesn't, on 8 GB.
- **Switch thinking off, or give it room.** Both models think by default. With a 512-token
  answer limit, Granite spent all of it thinking and returned an empty answer. The
  benchmark and the workflow turn thinking off. The benchmark also counts answers that were
  cut off, so this can't pass unnoticed.
- **Over-long input is refused, not truncated.** Ollama 0.34 returns an "exceeds the
  available context size" error. The n8n workflow checks length first, so the family sees
  "this meeting is too long for the current setting" instead of a raw server error.
- **On a Mac mini with 32 GB or more**, the spill-over seen here goes away at these sizes.
  That makes a bigger model or a longer context affordable, which is the first thing to
  re-measure.
