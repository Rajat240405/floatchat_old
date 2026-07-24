# FloatChat Frontend

Modern AI conversational interface for querying live Argo BGC oceanographic data.

## Tech Stack

- **Next.js 15** — React framework
- **TypeScript** — Type safety
- **Tailwind CSS** — Utility-first styling (with clsx + tailwind-merge)
- **Axios** — HTTP client
- **MapLibre GL (react-map-gl)** — Interactive map
- **Plotly.js** — Scientific visualization
- **Framer Motion** — Animations
- **Lucide React** — Icons

## Prerequisites

1. Backend running on `http://127.0.0.1:8000`
2. Node.js 20+ and npm/pnpm/yarn

## Quick Start

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Backend Connection

The frontend calls the backend **directly** (no Next.js proxy/rewrites are
configured in `next.config.js`). The base URL is taken from
`NEXT_PUBLIC_BACKEND_URL`, falling back to `http://127.0.0.1:8000`:

- `POST {BACKEND_URL}/api/v1/chat`
- `GET {BACKEND_URL}/health`

The backend enables CORS for `http://localhost:3000` / `http://127.0.0.1:3000`,
so the dev server can call it cross-origin.

Ensure the FloatChat backend is running before using the frontend:

```bash
cd ../floatchat
source .venv/bin/activate
uvicorn floatchat.api.main:app --host 127.0.0.1 --port 8000
```

## Project Structure

```
frontend/
├── app/
│   ├── page.tsx          # Main page with layout
│   ├── layout.tsx        # Root layout (dark mode)
│   └── globals.css       # Tailwind + custom styles
├── components/
│   ├── Layout/
│   │   ├── Header.tsx    # App header with branding
│   │   └── MainLayout.tsx # Page shell
│   ├── Chat/
│   │   ├── ChatPanel.tsx # Chat container
│   │   ├── ChatHistory.tsx # Message list
│   │   ├── ChatMessage.tsx # Individual message bubble
│   │   └── TypingIndicator.tsx # Loading dots
│   ├── Map/
│   │   └── MapPanel.tsx  # MapLibre map
│   ├── Results/
│   │   ├── ResultsPanel.tsx # Results container
│   │   ├── SummaryCards.tsx # Data summary cards
│   │   └── PlotlyChart.tsx # Plotly renderer
│   └── Input/
│       └── PromptInput.tsx # Message input bar
├── hooks/
│   └── useChat.ts        # Chat state management hook
├── services/
│   └── api.ts            # Axios API client
├── types/
│   └── index.ts          # TypeScript types
├── lib/
│   └── utils.ts          # Utilities (cn, id, time)
└── next.config.js        # Next.js config (reactStrictMode only — no rewrites)
```

## Features

- **Dark mode by default** — Ocean-inspired color palette
- **Interactive map** — MapLibre GL with OpenStreetMap tiles (dark styled)
- **Real-time chat** — Connected to live backend
- **Plotly rendering** — Scientific visualizations from backend JSON
- **Summary cards** — Profile count, measurements, date range, intent
- **Loading states** — Typing indicator, disabled input
- **Error handling** — Structured error messages from backend
- **Auto-scroll** — Chat scrolls to latest message
- **Responsive** — Adapts to viewport size
- **Animations** — Framer Motion for smooth transitions

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | `http://127.0.0.1:8000` | Base URL of the FloatChat backend (used directly; no Next.js proxy) |

Optional for local development — only set it when the backend is not on the
default address, e.g. `NEXT_PUBLIC_BACKEND_URL=http://your-backend:8000`.
Because this is a `NEXT_PUBLIC_` variable it is inlined at build time.

## Build for Production

```bash
npm run build
npm start
```

## Troubleshooting

### "Cannot connect to backend"

Ensure the backend is running on port 8000:

```bash
curl http://127.0.0.1:8000/health
```

Should return a JSON payload whose `status` is `"ok"` (or `"degraded"` when no
data lake is configured yet), e.g.
`{"status":"ok","duckdb_ready":true,...}`.

### Map not loading

Check that the MapLibre stylesheet is imported. `components/Map/MapPanel.tsx`
includes:

```ts
import "maplibre-gl/dist/maplibre-gl.css";
```

### Plotly not rendering

Ensure `plotly.js-dist-min` is installed. The chart component dynamically imports Plotly to avoid SSR issues.
