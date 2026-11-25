# Social Media Agent

An AI marketing agent that writes posts, creates designs, waits for your approval, schedules them on
LinkedIn / Facebook / Instagram, and **learns from post results** to write better content over time.

## Status

| Stage | What | Status |
|---|---|---|
| 4 | Collect performance data + ML model | ✅ built (`notebooks/01_performance_model.ipynb`) |
| 5 | Rank drafts + feed insights to the AI writer | ✅ via the analytics connector |
| 1 | AI writes posts → review queue | ✅ agent + review-queue connector (needs a Claude API key to run) |
| 2 | Approval step | ✅ Review queue page in the app + terminal (`scripts/review.py`) |
| 3 | Design creation | ✅ designer connector in the Arvin Marketing Pro style (4 layouts) + Canva connector |
| 6 | Scheduling | ✅ Buffer (LinkedIn, Facebook, Instagram) with images hosted on Cloudinary; Meta direct as fallback |
| 7 | AI-drafted comment replies (with approval) | ✅ Meta connector + review queue (untested without a token) |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_dataset.py              # sample data -> data/processed/posts.csv
jupyter notebook notebooks/01_performance_model.ipynb   # run all: trains models/engagement_model.joblib
python scripts/check_connectors.py --smoke   # see connected apps (no API key needed)
python scripts/agent_chat.py                 # chat with the agent (needs ANTHROPIC_API_KEY in .env)
streamlit run app/streamlit_app.py           # the app: dashboard, AI agent, review queue, connections
```

## The app

`streamlit run app/streamlit_app.py` (port busy? add `--server.port 8610`)

- **Left panel: AI agent.** Chat with the agent: "Write a LinkedIn post about…", "What worked best?",
  "Draft replies to new comments". It uses the connectors, makes on-brand graphics, and puts drafts in the
  Review queue. Needs `ANTHROPIC_API_KEY`.
- **Dashboard:** posts, interactions, impressions and engagement rate from Buffer for LinkedIn, Facebook
  and Instagram (Buffer refreshes metrics daily), or from the direct Facebook & Instagram connection; weekly
  charts and recent posts. **Followers:** Facebook and Instagram counts come from the direct Facebook &
  Instagram connection (Buffer doesn't provide them); LinkedIn doesn't share stats with apps, so you
  upload a screenshot of LinkedIn > Analytics (**Update LinkedIn stats from a screenshot**): Claude reads
  followers, profile viewers, search appearances and post impressions, you confirm, and each upload adds to
  a follower history chart, stored permanently in a Google Sheet (see **Google Sheets setup**).
  **Save to ML dataset** adds those posts to the model's training data. Shows sample data until you connect.
- **Review queue (two approvals):** **1 · Captions**: edit and approve the caption (or reject with a note
  for the agent) → the graphic is created in your brand style → **2 · Graphics**: change the layout or text
  and regenerate if needed, pick the time (suggested time from your data, or the next Buffer queue slot) →
  **Approve & schedule** uploads the image to Cloudinary and schedules the post in Buffer.
- **Insights:** what the ML model learned, and the exact insights the agent gets.
- **Connections:** **Connect** buttons for Facebook & Instagram, LinkedIn, Canva and Google Drive (each opens
  that service's own sign-in page), plus the Claude status. Each service needs an app you register once;
  the page's **Setup** box shows the steps, the redirect URL, and which keys to add.

No API key yet? Click **Load demo drafts** on the Review queue (or `python scripts/seed_demo_drafts.py`).

### Post graphics

The designer connector draws 1080×1080 images in the Arvin Marketing Pro style (navy, gold, white, Poppins
and Bebas Neue fonts bundled in `assets/fonts`): **cover** (carousel first slide), **list** (numbered tips),
**question** (condensed hook) and **card** (email style). Brand name, handle, website and colors live in
`brand.json`. Save your real logo as a transparent PNG at `assets/logo.png` to use it instead of the drawn one.

## Buffer + Cloudinary setup (posting, scheduling, analytics)

1. In Buffer, connect your LinkedIn profile, Facebook Page and Instagram account.
2. **publish.buffer.com → Settings → API** → create a key → `BUFFER_API_KEY`.
3. Sign up free at **cloudinary.com** → copy the **API environment variable** (`cloudinary://...`) →
   `CLOUDINARY_URL`. Buffer needs a permanent public image link and can't use Google Drive share links.
4. Set `APP_TIMEZONE` (e.g. `Asia/Manila`).
5. Check it: `python scripts/buffer_check.py` (read-only; lists channels and recent post metrics).
   On the Connections page you can pick which Buffer channel each platform posts to.

Buffer's API docs don't confirm every field name yet, so if `buffer_check.py` shows an API error, send it
over and the query can be adjusted.

## Google Sheets setup (permanent storage)

Streamlit Cloud's disk resets on every restart, so the LinkedIn history is saved in a Google Sheet through a
Google **service account** (a robot account only this app uses; it never expires).

1. console.cloud.google.com → pick/create a project → **APIs & Services → Library → Google Sheets API → Enable**.
2. **IAM & Admin → Service Accounts → Create service account** → name it → **Done**.
3. Open it → **Keys → Add key → Create new key → JSON** (a `.json` file downloads; keep it private).
4. Create a Google Sheet, click **Share**, add the service account's email (`client_email` in the JSON) as **Editor**.
5. Secrets:
   ```toml
   DATA_SHEET_URL = "https://docs.google.com/spreadsheets/d/..."
   GOOGLE_SERVICE_ACCOUNT_JSON = '''
   { ...the whole .json file... }
   '''
   ```
   (A `[gcp_service_account]` section with the JSON's fields works too.) Then **Connections → Google Sheets →
   Test connection**. The app creates a **LinkedIn** tab and adds one row per day you save.

## Deploy on Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and click **Create app**.
2. Repo `arv009/social-media-agent`, branch `main`, main file **`app/streamlit_app.py`**
   (`app/review_app.py` still works too). Python 3.12. Packages come from `app/requirements.txt`.
3. **Advanced settings > Secrets** (same keys as `.env.example`), for example:
   ```toml
   APP_PASSWORD = "choose-a-password"
   APP_URL = "https://your-app-name.streamlit.app"
   ANTHROPIC_API_KEY = "sk-ant-..."
   META_APP_ID = "..."
   META_APP_SECRET = "..."
   ```
4. Register `APP_URL` (with a trailing slash) as the redirect URL in each service's developer settings,
   then use the **Connect** buttons on the Connections page.

Keep in mind: Streamlit Cloud's disk is temporary. The review queue and connected-account tokens reset
when the app restarts or redeploys (connect again after a restart). For real use, move them to a database.

**Mac note:** this folder is on an iCloud-synced Desktop. The Python environment lives in `.venv.nosync`
(iCloud skips folders ending in `.nosync`) and `.venv` points to it; otherwise iCloud offloads the library
files and the app takes minutes to start.

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
app/              streamlit_app.py (entry), views/ (pages), agent_panel.py, agent_runtime.py
assets/fonts/     Poppins + Bebas Neue (open font license) for on-brand graphics
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
  connections.py  Connect buttons: OAuth for Meta, LinkedIn, Canva, Google Drive
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
