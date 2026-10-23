# AISO growth agent: Café Athena

This agent helps Café Athena (Pacific Beach, San Diego) get recommended by AI assistants. It runs a loop of four stages: Discovery, then Analysis, then Action, then Measurement.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...      # any subset of these works
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
export PERPLEXITY_API_KEY=...
python cli.py demo                # full loop offline with FAKE data, to check that everything runs
rm -rf out                        # clear demo data before the real run
```

Model names can be overridden with `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL`, and `PERPLEXITY_MODEL`.

## Real run order

| Step | Command | Output |
|---|---|---|
| 1. Discovery | `python cli.py discover --platforms claude-web,gpt,gemini-web,perplexity` | `out/query_bank.json` (frozen), every answer in `out/aiso.db` |
| 2a. Scorecard | `python cli.py score` | `out/scorecard.json`, which covers mention rate, top-3 rate, average rank, share of voice, and breakdowns by category and platform |
| 2b. Audit | Add the top rivals from the scorecard to `COMPETITOR_SITES` in `aiso/config.py`, then run `python cli.py audit` | `out/audit.json`, which records JSON-LD types, FAQ/menu schema, word count, and topic coverage |
| 2c. Diagnosis | `python cli.py diagnose` | `out/diagnosis.json`, a prioritized list of gaps with evidence, plus an off-site checklist |
| 3a. Content | `python cli.py generate` | `out/content/<ts>/`, containing the JSON-LD schema, FAQ, About copy, landing pages, meta description, and outreach drafts |
| 3b. Approval | `python cli.py approve [--repo ../site]` | `out/publish/`, an approval log, and optionally a git branch ready to open as a PR |
| 4a. Simulated lift | `python cli.py simulate --platforms claude,gpt` | before/after table, measured the same day |
| 4b. Trend | `python cli.py trend` and `streamlit run dashboard.py` | time series of all runs |
| Schedule | `.github/workflows/aiso-weekly.yml` | re-runs Discovery weekly |

## Design choices worth telling the judges

- **Frozen query bank.** The bank holds 25 San Diego queries across six intents. It is written to disk once, so every later run measures exactly the same questions.
- **Two ways to answer.** The `-web` variants and Perplexity use live web search, which mirrors what consumers actually see. The bare-model variants show what the models "remember" from training. Comparing the two separates a retrieval problem from a training-data problem.
- **Facts-only generation.** All copy comes from `config.RESTAURANT`. Anything unknown becomes a `[TODO]` marker, and the approval step will not approve a file that still contains one.
- **Reversible actions.** Each file must be approved individually. Every decision is logged with a SHA-256 hash, and publishing goes out as a git branch or PR, so it can be undone.
- **Polite crawling.** The crawler respects robots.txt, sends an identifying user agent, waits 1.5 seconds between requests, and stops at 6 pages per site. Yelp, TripAdvisor, Google Business Profile, and Reddit are not scraped because of their terms of service. They are covered by a manual checklist instead, and their official APIs can be plugged in if you have access.

## Honest limitations

- The simulated before/after is a controlled estimate of how a retrieval-based assistant would respond to the new content. It does not prove that live rankings changed. Real proof comes from the weekly live re-runs after search engines re-crawl the site.
- LLM answers vary from one run to the next. Treat category rates computed from fewer than 10 answers as directional, and use `--per-template 2` or more for tighter numbers.
- Demo mode uses fake competitors ("Competitor A Taverna" and so on) and placeholder site text. Never present demo numbers as real.

## 3-minute demo script

1. **Broken (45 seconds).** Show the dashboard for the live baseline. For example: "Café Athena shows up in X% of answers, but in 0% of rehearsal-dinner or date-night questions. These are the rivals that win those questions instead."
2. **Why (45 seconds).** Walk through the top 3 diagnosis gaps and the evidence for each, such as a missing schema, no events page, or a rival with FAQ content.
3. **Fixed (45 seconds).** Open the generated JSON-LD and the events page, then show the approval prompt and the git branch it created.
4. **Proof (45 seconds).** Show the simulated before/after table, the weekly schedule, and the trend chart that keeps growing.

## No API keys? Manual mode

You can collect real answers from the chat apps you already pay for, such as claude.ai, Gemini, or ChatGPT.

```bash
python cli.py manual-export --platform claude-chat --limit 12   # 12 queries, balanced across categories
open -e out/manual/claude-chat.txt                              # paste each answer under its header
python cli.py manual-import --platform claude-chat              # parse and score
```

Use a new chat for every query. An incognito or temporary chat is best, so memory doesn't bias the answer. Turn web search on, and paste the query exactly as written. To combine the answers with a Gemini API run in one scorecard, add `--into <run_id>` to the import command.

## Who beats Café Athena, by how much, and why

```bash
python cli.py leader                      # uses the latest live run, or add --run <id>
python cli.py leader --css report.html    # copy styles from an existing report
```

The command prints the overall leader and the leader of each category. For each one, it shows the mention-rate gap in points, the average rank, how many answers named the leader without Café Athena, and the head-to-head order when both appear. It then explains why, using three kinds of evidence:

1. **What the assistants said.** Sentences about the leader are tagged with themes such as happy hour, patio, private events, or reviews, and compared with what the assistants say about Café Athena.
2. **What they cited.** Sources come from Claude web search, Perplexity, and Gemini grounding.
3. **What the websites cover.** This needs `audit` to have been run, with the leader listed in `COMPETITOR_SITES`.

Outputs go to `out/leader.json`, to `out/leader_report.html` (a standalone page), and to `out/leader_sections.html` (sections you can paste into report.html).

## Head to head and closing the gap

`python cli.py leader` now also compares Café Athena against **every restaurant that leads a category**. For each one, it shows:

- how far ahead that restaurant is;
- what assistants praise it for that they don't praise Café Athena for;
- where Café Athena is described better;
- which sources cite it more often;
- what its website covers that Café Athena's doesn't.

Each of those differences becomes a step in `out/plan.json`.

```bash
python cli.py generate                        # gap-driven content -> out/content/<ts>/
# fill in data/menu.json and data/reviews.json (templates are created for you)
# resolve every [TODO] in out/content/<ts>/*.md, then:
python cli.py approve                         # per-file approval; builds out/publish/cms/*.html
python cli.py publish --wordpress             # dry run
python cli.py publish --wordpress --live      # creates DRAFT pages (WP_URL, WP_USER, WP_APP_PASSWORD)
python cli.py unpublish                       # deletes exactly those drafts
```

| Spec item | File |
|---|---|
| About copy | `about.md` |
| Menu descriptions | `menu.md`, built from `data/menu.json` |
| FAQ page | `faq.md`, which adds questions for every category Café Athena loses |
| Schema: Restaurant, Menu, FAQPage, Review | `restaurant.jsonld`. Menu and Review are only included once real data is supplied. |
| Local landing pages | `page-*.md`, each opening with the question diners actually ask, followed by a quotable answer |
| Content ready for any CMS | `out/publish/cms/*.html` |
| Act: publish with permission | WordPress drafts, with a log and one-command rollback |
| Act: outreach | `outreach-<domain>.md`, one per site that cites a leader but not Café Athena |
| Reviews | `review-request.md`, which follows Google's rules and excludes Yelp, since Yelp asks businesses not to solicit reviews |
| Why each piece exists | `action_plan.md` |

## Real search demand from Google Trends

Google Trends doesn't allow automated access, so you export the data by hand and import the file:

1. Open trends.google.com, then Explore. Enter a restaurant term, such as `greek restaurant`, `happy hour`, or `mediterranean food`.
2. Set the location to San Diego (or California), the time range to the past 12 months, and the category to Food & Drink.
3. In the **Related queries** panel, click the download icon. Do this for both Top and Rising.
4. Run `python cli.py trends-import ~/Downloads/relatedQueries.csv`.

The importer keeps only food and drink queries. It rewrites "near me" as "in Pacific Beach, San Diego" and tags each query with its Trends value.

## Teammate's Claude report, merged

`aiso/teammate/claude_2026-10-23.json` holds the aggregate results from the teammate's report: 47 Claude answers, a live audit of cafeathena.com, cited sources, and a name variant. `leader` now does the following with it:

- shows a **"Two assistants, one story"** table comparing our runs with the teammate's Claude results;
- turns the teammate's "Missing" cited pages and the "Athenas Catering" name variant into actions.

From the teammate's approach, the agent also gained:

- **booking-value weighting.** This uses `BOOKING_VALUE` in `config.py`, where events are about $2,000 and lunch about $30. The action plan is ranked by dollars at stake.
- **new request types:** catering and lunch.
- **new site checks in `audit`:** AI crawlers blocked in robots.txt, a missing `llms.txt`, and whether menu prices are readable as text or locked in a PDF.
- **`python cli.py sources`,** which visits the pages assistants cite and checks whether Café Athena is listed on them.
- **two new files from `generate`:** `llms.txt` and `gbp_description.txt` (for the Google Business Profile), plus `name-variants.md` for the owner to confirm.

To add another teammate's results, drop a JSON file with the same fields into `aiso/teammate/`.

## One team report

```bash
python cli.py consolidate        # -> out/team_report.html
```

This command merges the following into one report, organized around the five owner questions:

- the Gemini runs (read live from `out/aiso.db`)
- the teammate's Claude report
- the useful ideas from the dashboard prototype

It also produces a single action plan with a status for each step, and the `simulate` before/after results whenever they exist. The curated plan and findings live in `aiso/consolidated_inputs.json`.
