# org_packages: does an agent reach for the org's own library? (2026-10-17)

Yes, when it has read the list. Told what to build in an org whose packages it has never seen,
an agent named none of them on its own. After reading `org_packages`, it named the right one
for every task, on the tuning org and on the held-out one.

## What was tested

`org_packages` reads every active repo of an org over GitHub's API (each repo's file tree and
up to 150 manifests), and lists the libraries its repos use from one another. Each one comes with
where it is defined and how many repos use it. Two orgs:

| org | split | active repos | packages | cold read | requests | warm refresh |
|---|---|---|---|---|---|---|
| hashicorp | dev | 604 | 226 | 34.5 s | about 1,300 | 2.3 s (nothing pushed) |
| grafana | held | 533 | 192 | 56.7 s | about 2,350 | |

Each suite's `packages.yaml` lists tasks a developer there might start, written without the
library's name ("Make outbound HTTP calls retry automatically, with exponential backoff…"), with
the org's packages that serve each, checked against their repos. Ranked by how many repos use
them, each dev task's best answer is between 1st and 77th of hashicorp's 226 packages, and each
held task's between 4th and 53rd of grafana's 192.

Claude Haiku names the org libraries it would use, best first, up to three:

- **alone**: from the task and the org's name;
- **org-packages**: after reading the list a first `org_packages` call returns (kept beside the
  key as `org_packages.md`);
- **-masked**: the same two, with the org renamed (`veltrix`) in the task and the list, and its
  answers renamed back before scoring. hashicorp's and grafana's libraries are public and in the
  model's training data; a private org's are not, and masking stands in for that.

The answers are kept in `agent_picks.yaml` and never edited. A pick counts when it names an
answer in full, by its last path parts (`go-hclog`), or as a package inside it
(`terraform-exec/tfexec`).

## Method

- **Tuned on dev, run once on held.** The one setting tuned was how many packages a call lists.
  At 40 (5,700 characters), masked hit@1 on dev was 0.62: exactly the share of answers in the
  list. The agent picked every listed answer and never guessed one that wasn't there. At 100
  (13,600 characters) and with all 227 (28,200), it was 1.00. The default became 100. Held was
  then read and run once.
- **No judging.** An answer is a package name, checked against the package's own description
  or README before any run.

## Results

hit@k: share of tasks whose answer is among the first k picks. "In the list": share of tasks
with an answer in the list the agent read.

| split | agent | n | hit@1 | hit@3 | MRR | in the list |
|---|---|---|---|---|---|---|
| dev | alone | 26 | 0.96 | 0.96 | 0.96 | 1.00 |
| dev | org-packages | 26 | 1.00 | 1.00 | 1.00 | 1.00 |
| dev | alone-masked | 26 | 0.00 | 0.00 | 0.00 | 1.00 |
| dev | **org-packages-masked** | 26 | **1.00** | 1.00 | 1.00 | 1.00 |
| held | alone | 14 | 0.93 | 1.00 | 0.96 | 1.00 |
| held | org-packages | 14 | 1.00 | 1.00 | 1.00 | 1.00 |
| held | alone-masked | 14 | 0.00 | 0.00 | 0.00 | 1.00 |
| held | **org-packages-masked** | 14 | **1.00** | 1.00 | 1.00 | 1.00 |

The list the agent read: 13,660 characters on dev (about 3,400 tokens), 11,761 on held.

## How to read it

- **For a public org, the list adds little.** Haiku already knew hashicorp's libraries (0.96
  alone). That is a ceiling no private org gets: masked, the same agent named none of them.
- **For a private org, the list is the whole answer.** Masked, the agent found what the list
  showed, and only that: at 40 lines it missed exactly the tasks whose package was cut off.
  Whether an agent finds a library is mostly whether the list shows it.
- **Past the first 100.** Both keys' answers fall within the 100 most shared packages, so they
  don't test the rest. A package that only one or two repos use is found with `query` ("cron",
  "kms"), which this run doesn't measure.
- **Where it is used.** A `name` call adds which repos use the package and up to five files that
  import it, from one code search (about 0.3 to 1.7 s). Those files are where an agent sees how
  sibling repos call it. This run doesn't score them.
- **What changed between runs.** A review before the final runs skipped manifests under
  `examples/`, `testdata/` and `fixtures/`, made a private `package.json` define nothing, and
  kept a failed re-read from erasing what was known. Both lists were read again with that
  code, and the dev picks that depend on the list were asked again (1.00 before and after).
  Held then ran once.
- **Speed.** The cold read is about one request per repo plus one per manifest, 16 at a time.
  grafana's took longer for its monorepos (grafana/grafana alone has 83 manifests). After the
  first read, a day-old cache costs the listing plus the repos pushed since. A call that would
  dip under 500 requests left stops, keeps the rest for later, and says so.
