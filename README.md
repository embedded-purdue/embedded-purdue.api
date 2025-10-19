
---

# Embedded Systems Portal API

Serverless backend for the **Embedded Systems Member Portal**.
Deployed on **Vercel** and consumed by the static frontend hosted on **GitHub Pages**.

---


* `GET /api/events` — Fetch upcoming events from Google Calendar
* `POST /api/events` — Create a new calendar event (admin only)
* `GET /api/media` — List uploaded media (images / markdown)
* `POST /api/media` — Upload files to **Vercel Blob**, store metadata in **Vercel KV**

All responses include CORS headers for the GitHub Pages frontend.

---

## 🔧 Setup

### 1. Environment Variables

| Variable              | Description                                                            |
| --------------------- | ---------------------------------------------------------------------- |
| `ALLOWED_ORIGIN`      | Full URL of GitHub Pages site (e.g. `https://username.github.io`) |
| `ADMIN_TOKEN`         | Secret token required for `POST` requests                              |
| `GOOGLE_CALENDAR_ID`  | Calendar ID or email                                                   |
| `GOOGLE_CLIENT_EMAIL` | Google service account email                                           |
| `GOOGLE_PRIVATE_KEY`  | Service account private key (use `\n` for newlines)                    |

Also enable **Vercel KV** and **Vercel Blob** integrations.

---

## 📁 File Structure

```
app/api/
 ├─ events/route.ts     # Google Calendar endpoints
 └─ media/route.ts      # File upload + list endpoints
lib/
 ├─ gcal.ts             # Google Calendar logic
 ├─ media.ts            # Blob/KV helpers
 ├─ cors.ts             # CORS headers
 └─ admin.ts            # Admin auth check
```

---

## 🔐 Usage

Frontend requests must originate from `ALLOWED_ORIGIN`.

```bash
# List events
GET /api/events

# Create event (admin only)
POST /api/events
Authorization: Bearer <ADMIN_TOKEN>

# List media
GET /api/media

# Upload media (admin only)
POST /api/media
Content-Type: multipart/form-data
Authorization: Bearer <ADMIN_TOKEN>
```

---
