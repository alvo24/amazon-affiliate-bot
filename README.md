# 🛒 Amazon Affiliate Bot

Automated affiliate marketing bot that pulls **trending / bestselling products** from
your [Amazon Associates](https://affiliate-program.amazon.com/) account and posts
them to **Facebook Pages**, **Instagram Business**, and **Pinterest** on a schedule
you choose.

Designed to be *simple*: one FastAPI app, SQLite storage, a built-in scheduler
(APScheduler), and a minimal web dashboard. Deploy it to Fly.io, Railway, Render,
or any VPS with Docker.

---

## Features

- **Amazon PA-API 5.0** integration — fetches bestsellers from the Amazon browse
  nodes (categories) you choose.
- **Auto-generates affiliate links** with your Associates Partner Tag.
- **Posts to Facebook Page, Instagram Business, and Pinterest** via their
  official Graph / v5 APIs.
- **Customizable caption template** with placeholders for title, price, features,
  and affiliate URL.
- **Scheduled runs** via a standard cron expression (default: 9am, 1pm, 6pm).
- **Dry-run mode** with realistic mock products so you can see everything work
  end-to-end before you have API keys.
- **Web dashboard** for status, next-run time, manual "Run now", recent posts
  and products, plus password-protected login.
- **Deduplication** — a product successfully posted to a given platform will not
  be re-posted there.

---

## Quick start

### 1. Clone + install

```bash
git clone https://github.com/alvo24/amazon-affiliate-bot.git
cd amazon-affiliate-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Edit `.env`

At minimum set `APP_ADMIN_PASSWORD` and `APP_SECRET`. Leave `DRY_RUN=true` while
you're still wiring up credentials — the bot will return mock products and skip
publishing.

### 3. Run it

```bash
uvicorn app.main:app --reload
```

Open <http://localhost:8000>, log in, and click **Run now** to verify the
dry-run path end-to-end.

### 4. Add credentials and flip `DRY_RUN=false`

See the [Setting up credentials](#setting-up-credentials) section below.

---

## Setting up credentials

### Amazon Associates + Product Advertising API 5.0

1. Sign up for [Amazon Associates](https://affiliate-program.amazon.com/) and
   get approved (**note**: Amazon now requires 3 qualifying sales within the
   first 180 days — until then PA-API requests will be rejected).
2. Once approved, go to the Associates portal → **Tools → Product Advertising
   API** and request keys.
3. Fill in `AMAZON_ACCESS_KEY`, `AMAZON_SECRET_KEY`, and `AMAZON_PARTNER_TAG`
   (your store ID — looks like `yourname-20` in the US).
4. Pick categories (browse nodes) from <https://www.browsenodes.com> and set
   them as a comma-separated list in `AMAZON_BROWSE_NODES`.

### Facebook Page

1. Create / choose a Facebook Page.
2. Create an app at <https://developers.facebook.com/apps/>.
3. In **Graph API Explorer**, generate a **Page Access Token** with
   `pages_manage_posts` and `pages_read_engagement` scopes.
4. Convert it to a **long-lived token** (see
   [Meta docs](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/)).
5. Put it in `FACEBOOK_PAGE_ACCESS_TOKEN` and your numeric page ID in
   `FACEBOOK_PAGE_ID`.

### Instagram Business

Instagram only allows automated publishing from **Business** (or Creator) accounts
that are linked to a Facebook Page.

1. Convert your IG account to Business and link it to the same FB Page above.
2. Using the same Meta app, request scopes
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`.
3. Fetch the IG Business Account ID via
   `GET /{page-id}?fields=instagram_business_account`.
4. Set `INSTAGRAM_BUSINESS_ACCOUNT_ID` and `INSTAGRAM_ACCESS_TOKEN`.

> ⚠️ Instagram *requires* a publicly reachable image URL. The bot will skip
> products without `image_url`. Amazon image URLs returned by PA-API are public.

### Pinterest

1. Go to <https://developers.pinterest.com/apps/> and create an app.
2. Generate an access token with scopes `boards:read`, `pins:read`, `pins:write`.
3. Create a board for your affiliate pins and copy its ID.
4. Set `PINTEREST_ACCESS_TOKEN` and `PINTEREST_BOARD_ID`.

---

## How scheduling works

The bot ships with an in-process [APScheduler](https://apscheduler.readthedocs.io/)
that runs on the cron expression in `POST_SCHEDULE_CRON` (default:
`0 9,13,18 * * *` = 9am / 1pm / 6pm in the `TIMEZONE` you set).

Every run:

1. Asks PA-API for bestsellers across your configured browse nodes (up to
   `AMAZON_MAX_ITEMS`).
2. For each product, for each enabled platform in `ENABLED_PLATFORMS`, posts if
   it hasn't been successfully posted there already.
3. Writes a row to the `post` table with the remote ID (or error) and a row to
   `run_log` summarising the run.

You can also hit **Run now** from the dashboard at any time.

---

## Running with Docker

```bash
docker build -t amazon-affiliate-bot .
docker run --rm -p 8000:8000 --env-file .env -v $(pwd)/data:/data amazon-affiliate-bot
```

## Deploying to Fly.io

```bash
# one-off
fly launch --copy-config --no-deploy
fly volumes create affiliate_data --size 1
fly secrets set $(grep -v '^#' .env | xargs)
fly deploy
```

The included `fly.toml` mounts a 1 GB volume at `/data` for SQLite persistence.

---

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## Project layout

```
app/
  main.py          # FastAPI app + dashboard routes
  config.py        # pydantic-settings
  db.py            # SQLite engine + init
  models.py        # SQLModel tables: Product, Post, RunLog
  amazon.py        # PA-API client (real + mock)
  scheduler.py     # APScheduler wiring
  service.py       # run_once() — orchestrates fetch + post
  publishers/
    base.py
    facebook.py
    instagram.py
    pinterest.py
templates/         # Jinja2 server-rendered UI
static/            # CSS
tests/             # pytest unit tests
```

## Compliance notes

- Always disclose affiliate relationships in captions (the FTC requires it).
  The default caption template already contains `#affiliate` — keep it.
- Amazon Associates has an [Operating Agreement](https://affiliate-program.amazon.com/help/operating/agreement)
  that limits how/where you can post. Review it before going live.
- Don't store or cache Amazon prices for longer than 24 hours (PA-API TOS).
  This bot re-fetches on every run.

## License

MIT
