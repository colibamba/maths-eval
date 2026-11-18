# Maths Word-Problem Eval (version 2)

A small harness that tests how well different AI models solve maths word problems.

## What's in here

- `questions.json`: the test set, with 35 questions. Each has an id, a difficulty, a category, and the correct answer.
- `run_eval.py`: sends each question to each model, grades the answers, and prints results tables.
- `results/`: created when you run it. Every run saves all the raw model replies here.

## Question categories

| Category | What it tests |
|---|---|
| `standard` | Ordinary word problems (q01–q08) |
| `famous` | Well-known trick puzzles the models have probably seen online (q09, q10, q12) |
| `perturbed` | The same tricks with new names and numbers (q13–q17). If a model aces `famous` but fails `perturbed`, it has memorised the answers rather than reasoning them out. |
| `distractor` | Questions padded with irrelevant details (q18–q20). Can the model ignore the noise? |
| `multi-step` | Problems needing several careful steps (q11, q21–q35) |

## Setup (Windows)

1. Install Python from python.org. Tick **"Add Python to PATH"** in the installer.
2. Install Ollama from ollama.com/download.
3. Open PowerShell in this folder and run:
   ```
   py -m pip install ollama
   ollama pull llama3.2
   ollama pull qwen2.5:7b
   ollama pull qwen2.5:14b
   ```

## Running it

Test the harness with a fake model (no Ollama needed):
```
py run_eval.py --models mock
```

Run the real thing:
```
py run_eval.py --models llama3.2 qwen2.5:7b qwen2.5:14b
```

Re-score a saved run without asking the models again (you can list several files):
```
py run_eval.py --regrade results\<run-folder>\responses.jsonl
```

## Choosing the prompt

`--prompts` sets the instructions the models get:

| Prompt | What the model is told |
|---|---|
| `default` | Think step by step (but it can skip the working). Used if you don't choose one. |
| `working` | You MUST show every calculation before answering. |
| `direct` | Do NOT show any working; give only the answer line. |

## Experiment: does working out cause better answers?

In run 2, qwen2.5:7b was right 90% of the time when it showed working and 50% when it didn't. But the model *chose* when to show working, so that doesn't prove the working caused the difference. Maybe it skipped the working on questions that were harder for it anyway.

To test it properly, run each model on every question twice: once forced to show working, once forbidden. Then the prompt is the only thing that changes.

```
py run_eval.py --models qwen2.5:7b llama3.2 --prompts working direct
```

This prints an extra table, **Experiment: forced working vs forced direct**. Look at the two middle columns:
- **only working right:** questions the model got right only when it showed working.
- **only direct right:** questions it got right only when answering straight away.

If "only working right" is much bigger, working out really does help. Also check the **Did showing working help?** table to confirm the models obeyed: `[working]` should show working on every question and `[direct]` on none. If a model ignored the instruction, say so in your findings.

## Reading the results

The script prints these sections:

1. **Results:** overall score, score by difficulty, average seconds per question, and how often the model ignored the `ANSWER:` format. Each model now gets an untimed warm-up question first, so loading time no longer skews the timings.
2. **Score by category:** compare `famous` with `perturbed` to check for memorisation.
3. **Did showing working help?:** splits each model's answers into ones that showed working and ones that jumped straight to an answer, and scores each group. A reply counts as "showed working" if it has at least 40 characters before the ANSWER line.
4. **Experiment** (only when you run both `working` and `direct`): question-by-question comparison of the two prompts.
5. **Mistakes:** every wrong answer, and whether the model showed its working.

## Findings

### Run 1 (12 questions)

| Model | Score | Avg secs |
|---|---|---|
| llama3.2 | 12/12 | 1.8 |
| qwen2.5:7b | 9/12 | 7.7 |
| qwen2.5:14b | 11/12 | 46.6 |

- The smallest model scored highest, so the test was too easy and too small to separate the models.
- qwen2.5:7b skipped its working on 6 questions and got 3 of them wrong. It got all 6 right when it showed working.
- qwen2.5:14b used the right method on q02 but dropped an hour while adding up.
- Timings included model loading time (fixed in version 2).

### Run 2 (35 questions, default prompt)

| Model | Score | Avg secs |
|---|---|---|
| qwen2.5:14b | 34/35 (97%) | 41.6 |
| llama3.2 | 32/35 (91%) | 1.6 |
| qwen2.5:7b | 26/35 (74%) | 3.9 |

- **Possible memorisation:** llama3.2 got the famous widgets puzzle right (q10) but the perturbed printers version wrong (q14, answered 40). One pair of questions only, so a hint rather than proof.
- **Distractors work:** llama3.2 multiplied the bakery's rolls by its number of staff (q20, answered 606).
- **Midnight is hard:** both small models got q29 (22:50 to 01:20) wrong.
- **Working out:** qwen2.5:7b was right on 19/21 questions when it showed working (90%) and 7/14 when it didn't (50%). The model chose when to skip working, so this needs the controlled experiment above.
- **Too close to call:** qwen2.5:14b vs llama3.2 is a 2-question difference out of 35, which is within noise. llama3.2 is about 25 times faster.
- **Repeatable:** with temperature 0, llama3.2 and qwen2.5:14b gave word-for-word the same answers as run 1.

### Run 3 (experiment: forced working vs forced direct)

| Model | Forced working | Forced direct | Default prompt (run 2) |
|---|---|---|---|
| qwen2.5:7b | 32/35 (91%) | 12/35 (34%) | 26/35 (74%) |
| llama3.2 | 30/35 (86%) | 9/35 (26%) | 32/35 (91%) |

Question by question:

| Model | Both right | Only right with working | Only right without | Both wrong |
|---|---|---|---|---|
| qwen2.5:7b | 11 | **21** | 1 | 2 |
| llama3.2 | 7 | **23** | 2 | 3 |

- **Working out causes better answers.** On the same questions, with only the prompt changed, working beat direct 21 to 1 (Qwen) and 23 to 2 (Llama). If the prompt made no difference, a split that lopsided would happen by chance less than 1 time in 50,000 (sign test).
- **The models obeyed the prompts.** Every forced-working reply showed working. Every forced-direct reply skipped it, apart from one Llama reply.
- **Forcing working fixed Qwen 7B:** from 74% with the default prompt up to 91%. A one-line prompt change gained more than switching to a bigger model would.
- **More working isn't always better:** Llama scored slightly lower forced (86%) than with the default prompt (91%). Longer working gave it more chances to slip, for example 500 minutes on the widgets puzzle it previously got right. That's a 2-question difference, so within noise.
- **Format broke under pressure:** told to give only the answer, Qwen 7B dropped the ANSWER line on 14 of 35 questions. The fallback grader still read them.
- **Grading only the final number has blind spots:** in direct mode, Llama answered 27 on q31 (correct) but then wrote "Jake got 40 - 7 = 33 questions right". It was marked correct despite contradicting itself.
