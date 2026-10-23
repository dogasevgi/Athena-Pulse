# Running the customer website

## Try it locally (fake data, no keys)
    pip3 install -r requirements.txt
    DEMO_MODE=1 python3 server.py        # http://127.0.0.1:8000

## Go live
1. Get API keys for the providers you want measured (Anthropic, OpenAI, Gemini, Perplexity).
2. Deploy this folder with the included `Dockerfile` on Render, Fly.io or Railway.
   - Set the variables from `.env.example` in the host's dashboard (never commit real keys).
   - Attach a persistent disk/volume at `/data` so reports survive restarts.
   - Health check path: `/healthz` (`"ready": true` once a key is set).
3. Put it on your own domain and keep HTTPS on (the host does this for you).

## How it works
`POST /api/jobs` validates the form, creates `jobs/<id>/` and queues the agent. Each customer gets
a private folder, so runs never mix. The customer is sent to `/j/<id>` (progress), then `/r/<id>/`
(the report), which also offers `download.zip` with all the generated fixes. The id is a random
128-bit token: anyone with the link can view that report, nobody else can.

## Cost and safety controls
- Each report asks every configured provider `QUERIES_PER_JOB` questions once, plus one cheap
  parsing call per answer and a few writing calls. Check your providers' current pricing, then set
  `MAX_JOBS_PER_DAY` so the worst case is a number you are happy with.
- Per-IP daily limit, a hidden honeypot field, and an optional `ACCESS_CODE`.
- Customer-supplied URLs (and the pages AI answers cite) are fetched only if they resolve to public
  IPs, on ports 80/443, with redirects re-checked and a 2 MB size cap. Also block outbound access
  to your host's internal network/metadata address at the platform level as a second layer.
- Reports are served with a strict Content-Security-Policy; fix files show as plain text.
- Failures show the customer a generic message; the details are in `jobs/<id>/job.log`.

## Not included (decide before charging money or storing emails)
No accounts, payments, email delivery, or privacy policy/terms pages. The before/after experiment
and GitHub PR approval from the desktop tool are intentionally off for customers.
Live provider calls were not tested in the sandbox (no keys); run one real job and read
`jobs/<id>/job.log` before launch.
