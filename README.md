# Social Media Agent

An AI marketing agent that writes posts, creates designs, waits for your approval, schedules them on
LinkedIn / Facebook / Instagram, and **learns from post results** to write better content over time.

## Status

| Stage | What | Status |
|---|---|---|
| 4 | Collect performance data + ML model | ✅ built (`notebooks/01_performance_model.ipynb`) |
| 5 | Rank drafts + feed insights to the AI writer | ✅ via the analytics connector |
| 1 | AI writes posts → review queue | ✅ agent + review-queue connector (needs a Claude API key to run) |
| 2 | Approval step | ✅ Streamlit review page (`app/review_app.py`) + terminal (`scripts/review.py`) |
| 3 | Design creation | ✅ designer connector (local, from `brand.json`) + Canva connector (needs your Canva login) |
| 6 | Scheduling | ✅ Facebook/Instagram via the Meta connector (untested without a token); Buffer/LinkedIn ⏳ |
| 7 | AI-drafted comment replies (with approval) | ✅ Meta connector + review queue (untested without a token) |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_dataset.py              # sample data -> data/processed/posts.csv
jupyter notebook notebooks/01_performance_model.ipynb   # run all: trains models/engagement_model.joblib
python scripts/check_connectors.py --smoke   # see connected apps (no API key needed)
python scripts/agent_chat.py                 # chat with the agent (needs ANTHROPIC_API_KEY in .env)
streamlit run app/review_app.py              # review page: approve, edit, reject, publish
```

## Review page

`streamlit run app/review_app.py` opens a page with four tabs:

- **To review:** each draft with the agent's reasoning and predicted engagement. Edit the text and post
  time, then **Approve**, **Save**, or **Reject** with a note the agent reads when revising.
- **Approved:** **Publish now** / **Schedule** (Facebook, Instagram) once Meta is set up in `.env`.
  LinkedIn drafts are approved here and posted by hand until that connector exists.
- **History:** every draft and its status.
- **Insights:** engagement by platform, media type and topic, plus the exact insights the agent is given.

No API key yet? `python scripts/seed_demo_drafts.py` adds example drafts (`--clear` removes them).
If port 8501 is busy (e.g. another Streamlit app), add `--server.port 8610`.

## Deploy the review page on Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and click **Create app**.
2. Pick this repo, branch `main`, main file **`app/review_app.py`**. Python 3.12 is a safe choice.
   Packages come from `app/requirements.txt`.
3. Optional, under **Advanced settings > Secrets**, to enable publishing from the page:
   ```toml
   META_PAGE_ACCESS_TOKEN = "..."
   META_PAGE_ID = "..."
   META_IG_USER_ID = "..."
   ```
4. Open the app and click **Load demo drafts** to try the review flow.

Keep in mind: Streamlit Cloud's disk is temporary, so the review queue resets when the app restarts or
redeploys, and the agent (which runs on your computer) can't reach that copy. For real use, the queue
should move to a shared database later (e.g. Supabase or Google Sheets).

## Connectors (like Claude's connectors)

Each app is a small **MCP server** in `connectors/`. The agent (`src/social_agent/agent.py`) starts every
connector listed in `connectors/connectors.json` whose setup is complete, collects their tools, and lets
Claude decide which to call. Adding an app = add one server file + one entry in `connectors.json`.

```
          you ──► agent_chat.py ──► Claude (tool use)
                                       │
     ┌────────────┬─────────────┬──────────┼──────────┬─────────────┬──────────────┐
 analytics   review_queue    designer     canva       meta       google_drive   buffer/linkedin
 (ML model,  (drafts; human  (on-brand   (templates, (FB + IG:   (brand docs,    (planned)
  insights)   approves)       images)     edit,       comments,   assets)
                                          export)     publish)
```

| Connector | Tools | Setup |
|---|---|---|
| analytics | performance_summary, top_posts, content_insights, score_drafts, best_posting_times | Run the notebook once |
| review_queue | submit_post_draft, submit_reply_draft, list_drafts, get_draft, revise_draft | None |
| meta | list_recent_posts, list_comments, sync_metrics_to_dataset, publish_approved_post, send_approved_reply | `META_*` values in `.env` |
| google_drive | search_files, list_folder, read_file, upload_file | `secrets/google_credentials.json`, then `python scripts/google_login.py` |
| designer | brand_guidelines, make_post_graphic | Edit `brand.json` (name, handle, colors, fonts, logo, voice) |
| canva | list_brand_templates, get_template_fields, create_from_template, send_image_to_canva, export_design | See **Canva setup** below |

**Safety by design:** the agent has no "approve" tool. Publishing tools take only a draft id and refuse
anything a human hasn't approved (review page or `scripts/review.py`).

**Use them in Claude Desktop too:** copy the entries from `connectors/claude_desktop_config.example.json`
into Claude Desktop's config file (Settings > Developer > Edit Config), then restart Claude Desktop.

## Canva setup

1. Go to the [Canva Developer Portal](https://www.canva.com/developers/integrations) and create an integration.
2. Copy the **Client ID** and generate a **Client secret** into `.env` as `CANVA_CLIENT_ID` / `CANVA_CLIENT_SECRET`.
3. Under **Scopes**, enable: design:content (read + write), design:meta (read), asset (read + write),
   brandtemplate:meta (read), brandtemplate:content (read).
4. Under **Authentication > Redirect URLs**, add `http://127.0.0.1:3001/oauth/redirect`.
5. Run `python scripts/canva_login.py` and approve in the browser. The token is saved to `secrets/` and
   refreshed automatically.

What works on which plan (per Canva's docs): uploading images, creating designs and exporting work on any
plan. **Brand templates and autofill need Canva Pro, Teams or Enterprise.** Without them, the agent makes the
image with the designer connector and sends it to Canva so you can polish it.

Good to know: Canva edit links last 30 days; exported image links last **24 hours**. Instagram publishing
needs that public link, so export (`export_design`) close to publishing time.

## Using your real data

- **CSV exports:** download post analytics from LinkedIn, Meta Business Suite or Buffer into `data/raw/`.
  Put `linkedin`, `facebook` or `instagram` in each file name. If a column isn't recognised, add its name to
  `COLUMN_ALIASES` in `src/social_agent/loaders/csv_loader.py`.
- **Meta API:** copy `.env.example` to `.env`, fill in your Page token and IDs, then
  `python scripts/build_dataset.py --meta`.
- Once you have ~100+ real posts, use `--no-sample` (or `USE_SAMPLE = False` in the notebook).

## Folder layout

```
app/              review_app.py (Streamlit review page)
connectors/       MCP servers (one per app) + connectors.json registry
data/raw/         your analytics exports (not committed)
data/sample/      synthetic sample data (fake, for development)
data/processed/   posts.csv (combined standard table), insights_prompt.txt
data/review_queue.db   drafts waiting for / after review
data/exports/     generated and exported images
brand.json        brand name, colors, fonts, logo, voice
models/           trained model + comparison table
notebooks/        step-by-step notebooks
scripts/          build_dataset, check_connectors, agent_chat, review, seed_demo_drafts,
                  google_login, canva_login
secrets/          Google OAuth files (not committed)
src/social_agent/
  agent.py        ConnectorHub (starts connectors) + MarketingAgent (Claude tool-use loop)
  review_queue.py SQLite review queue; approve/reject is human-only
  publishing.py   publish approved drafts (used by the Meta connector and the review page)
  graphics.py     local on-brand image maker (Pillow)
  canva_api.py    Canva Connect API client (OAuth refresh, uploads, designs, exports, autofill)
  schema.py       the standard post table every source converts into
  features.py     feature engineering + engagement rate
  synthetic.py    sample data generator (with known "true" effects)
  model.py        train / evaluate / explain / rank drafts / insights
  loaders/        csv_loader.py, meta_api.py
```

## How the model works

- **Target:** engagement rate = (likes + comments + shares + clicks + saves) / impressions
- **Features:** platform, media type, topic, tone, day/hour, length, hashtags, emojis, question, call to action, link
- **Models compared:** platform-average baseline, Ridge, Random Forest, Gradient Boosting (time-based split)
- **Used for:** ranking AI drafts, suggesting posting times, and writing an insights block for the AI's prompt

Note: the sample data is synthetic. Results on it only show that the pipeline works, not real marketing findings.
