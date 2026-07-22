# FloatChat Frontend

Modern AI conversational interface for querying live Argo BGC oceanographic data.

## Tech Stack

- **Next.js 15** — React framework
- **TypeScript** — Type safety
- **Tailwind CSS** — Utility-first styling
- **shadcn/ui** — Component primitives (clsx, tailwind-merge, cva)
- **Axios** — HTTP client
- **React Leaflet** — Interactive map
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

The frontend connects to the backend via Next.js rewrites (proxy):

- `/api/chat` → `http://127.0.0.1:8000/api/v1/chat`
- `/api/health` → `http://127.0.0.1:8000/health`

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
│   │   └── MapPanel.tsx  # Leaflet map
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
└── next.config.js        # Next.js config with proxy rewrites
```

## Features

- **Dark mode by default** — Ocean-inspired color palette
- **Interactive map** — Leaflet with OpenStreetMap (dark styled)
- **Real-time chat** — Connected to live backend
- **Plotly rendering** — Scientific visualizations from backend JSON
- **Summary cards** — Profile count, measurements, date range, intent
- **Loading states** — Typing indicator, disabled input
- **Error handling** — Structured error messages from backend
- **Auto-scroll** — Chat scrolls to latest message
- **Responsive** — Adapts to viewport size
- **Animations** — Framer Motion for smooth transitions

## Environment Variables

None required for local development. The backend URL is configured via Next.js rewrites in `next.config.js`.

To change the backend URL, edit `next.config.js`:

```js
destination: 'http://your-backend:8000/api/v1/chat',
```

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

Should return `{"status":"ok","metadata_loaded":true}`.

### Map not loading

Check that Leaflet CSS is imported. The `globals.css` includes:

```css
@import "leaflet/dist/leaflet.css";
```

### Plotly not rendering

Ensure `plotly.js-dist-min` is installed. The chart component dynamically imports Plotly to avoid SSR issues.
