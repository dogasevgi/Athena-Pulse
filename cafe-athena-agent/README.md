# Café Athena: AI search growth agent

NYU SPS x Pulse Foundry Hackathon, Oct 23, 2026. Target: Café Athena, 1846 Garnet Ave, Pacific Beach, San Diego.

**Live dashboard:** https://claude.ai/artifact/XBRMkBFgXJYkerpgUSY1Gx
(also in this repo: `artifacts/dashboard_hosted.html`; open `artifacts/dashboard.html` locally for the Gemini "Ask live" tab)

## Results (Oct 23, 2026)

- **Where it ranks:** recommended in 11 of 111 AI answers (Claude 8 of 47 with web search; Gemini 3 of 64). Never recommended for
  private events, date night, happy hour or vegan/gluten-free questions; 10% of potential booking value on Claude, 1% on Gemini.
- **Why rivals win:** Pacific Beach AleHouse leads private events (~$8,000 of bookings in answers that left Café Athena out),
  Mr Greek leads catering, JRDN leads date night, happy hour and general questions. Café Athena's site passes 0 of 4
  machine-readable checks (Restaurant, FAQ, Menu schema, llms.txt), and guides the assistants cite list rivals instead.
- **What the agent produced (`artifacts/`):** Restaurant + Menu + FAQ schema, llms.txt, 6 fact-checked pages (events,
  catering menu, happy hour, date night, vegan/gluten-free, Greek food), FAQ, About copy, Google Business Profile text and
  outreach drafts. Every fact comes from Café Athena's own site and menus (`SOURCES_AND_CHECKS.md`); nothing publishes
  without owner approval (`act.py`, `wordpress.py --live` / `--undo`).
- **Measurement:** baseline recorded; the same questions are re-asked after publishing (`agent.py measure`). A controlled
  simulation showed the AI already recommends Café Athena once it reads the site, so the live problem is being found.

## Repo map

- `agent.py` runs the loop: discover/manual import -> analyze -> audit -> compare -> diagnose -> generate -> act -> report -> dashboard
- `answers/` recorded AI answers (Claude); Gemini answers are imported from the aiso_agent tool with `import_aiso.py`
- `tools/aiso_agent/` the Gemini collection, Google Trends import and simulation tool used alongside this agent
- `verified_content.json`, `SOURCES_AND_CHECKS.md` fact-checked content and the owner's checklist

# AI Search Optimization Agent (Café Athena)

> **Customer-facing website:** see `DEPLOY.md` (`server.py`). The sections below describe the local desktop tool.

## Easiest way: no coding
Double-click **Start Agent.command**. A control panel opens in your browser:
1. Check the restaurant details. 2. Pick where answers come from (free spreadsheets,
live AI keys, or practice data). 3. Click **Run the agent**. 4. Read the results and open the
full report. 5. Approve or skip each fix. 6. Re-measure later.
If macOS says the file can't be opened, right-click it, choose **Open**, then **Open** again.
Or in Terminal, from this folder: `python3 app.py`. Keep the Terminal window open while you use it.

Given a restaurant, the agent answers the owner's five questions:

| Question | Stage | What the agent does |
|---|---|---|
| Where do I rank in AI search? | Discovery | Asks Claude, ChatGPT, Gemini and Perplexity ~47 real diner questions, several times each; logs mentions, rank, competitors, cited URLs |
| Why are competitors beating me? | Analysis | Value-weighted scorecard, competitor share of voice, site audit, opens cited pages to see who's listed, checks hours/phone/name consistency |
| What should I change? | Analysis | Prioritized gaps, each backed by a number or URL |
| Can the agent make the changes? | Action | Writes schema, FAQ, landing pages, Google profile text and outreach emails; opens a GitHub PR / approves emails only after the owner says yes |
| Did my visibility improve? | Measurement | Controlled before/after test now; live re-measure later with `measure`, tracked over time |

## Free mode (no API key, no cost)

`answers/claude_2026-10-23.csv` already holds 11 real Claude answers (with web search, collected
Oct 23, 2026). Teammates fill in `answers/template.csv` by asking free ChatGPT, Gemini and
Perplexity the same questions (paste the answer; restaurants and sources are optional).

```bash
python3 agent.py --manual answers/*.csv
```
Everything runs: scoring, site audit, cited-page check, consistency check, rule-based diagnosis,
fact-only content. Only the simulated before/after test needs a key; measure for free by
re-asking after publishing fixes: `python3 agent.py measure --manual answers/week2/*.csv`.

## Merged from the team's aiso_agent tool

- **Gemini answers from aiso_agent:** `python3 import_aiso.py ~/Downloads/aiso_agent/out/aiso.db` writes
  `answers/gemini_aiso_<date>.csv`; then `python3 agent.py --manual answers/*.csv` analyzes Claude + Gemini together.
  Questions that aren't in `data/queries.json` get their request type and booking value from keywords.
- **Fact-checked content:** `verified_content.json` (5 pages, 10 FAQs, About, Google profile text) built only from
  cafeathena.com, its bar & happy hour menu, group dining page, Nov 2025 catering menu and Toast page.
  `generate.py` uses it for Café Athena instead of drafts with `[VERIFY]` gaps. Owner checks: `SOURCES_AND_CHECKS.md`.
- **Verified facts in `config.py`:** phone, email, reservations link, happy hour and cocktail menu with prices and
  diet tags. The schema now includes a real `Menu`, `telephone` and `acceptsReservations`; `llms.txt` is generated.
- **Head to head (`compare.py`, new report section):** for each rival that leads a kind of request: the gap, booking
  value lost, what answers praise it for vs. Café Athena, which sources cite it more, and what its website has.
- **Rival websites (`COMPETITOR_SITES` in `config.py`):** `audit.py` checks their schema, FAQ, llms.txt and menu prices.
- **Menu price check fixed:** the audit now reads every HTML menu page and counts prices written without "$"
  (Café Athena's bar menu lists "Athena ... 15"), so it no longer reports "no prices".
- **Gemini on the free tier:** waits as long as Google asks on 429s, says clearly when a model has zero free quota,
  and switches to an available Flash model if the default is retired. Tip: `export GEMINI_MODEL=gemini-3.5-flash-lite`.
- **Google Trends phrasings** added to the query bank (happy hour, "best restaurants in Pacific Beach", citywide Greek).
- **WordPress drafts:** `python3 wordpress.py` (dry run) / `--live` / `--undo`.

## Run it (Mac)

```bash
cd /path/to/athena-agent
pip3 install --user -r requirements.txt

python3 agent.py --demo          # 1. offline, fake data, no keys: see the whole loop work

export ANTHROPIC_API_KEY=sk-ant-...   # 2. add any of these you have
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
export PERPLEXITY_API_KEY=...

python3 agent.py --quick         # 3. live, small (8 queries x 1 run), ~5 minutes
python3 agent.py --act           # 4. live, full, then approve actions
python3 agent.py measure         # later: live re-measure, compared with baseline
```

The report opens automatically (`artifacts/report.html`). All generated files are in `artifacts/`.

**Another restaurant:**
```bash
python3 agent.py reset
python3 agent.py --name "Joe's Diner" --website https://joesdiner.com \
  --location "Mission Hills, San Diego, CA" --cuisine American \
  --highlight "Open since 1985" --highlight "Private room for 30"
```
Only facts you give are used; everything else becomes `[VERIFY: ...]`.

## Settings
- Only providers whose key is set are used. If a model name errors, override it:
  `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL`, `PERPLEXITY_MODEL`.
- `RUNS=1` halves API calls. Interrupted runs resume; finished calls aren't repeated.
- GitHub PR action: `export GITHUB_TOKEN=... GITHUB_REPO=owner/repo` (e.g. a mirror of the site).
- If an LLM step fails, diagnosis and content fall back to transparent rules and fact-only templates.

## Individual stages (for debugging)
`queries.py` → `discover.py` → `analyze.py` → `audit.py` → `diagnose.py` → `generate.py` → `act.py` → `experiment.py` → `report.py`, each with `--label baseline`.

## 3-minute demo
1. **Before (30s):** report hero: a real AI answer where Café Athena is missing.
2. **Why (60s):** "Where the money is" table, cited-sources table, the hours conflict.
3. **Fix (45s):** show the FAQ/schema/events page, approve one action live (`python3 act.py`).
4. **After (30s):** before/after experiment; `measure` keeps tracking weekly.
5. **Close (15s):** the five answers section, mapped to the problem statement.

## Say these caveats out loud
- AI answers vary run to run; that's why each query is asked multiple times.
- The before/after is a controlled retrieval simulation (same competitor pages in both arms,
  only our new page added). Live engines are re-measured with `measure` after publishing.
- Sites that block scraping are shown as "Not checked". Fix every `[VERIFY]` before publishing.
