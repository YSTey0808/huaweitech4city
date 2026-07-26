# frontend/

The chat UI — React + Vite + TypeScript + Tailwind CSS v4. Part of the `huaweitech4city` monorepo; see the [root README](../README.md) for the full system and [docs/frontend.md](../docs/frontend.md) for everything below in detail (structure, Realtime contract, env vars, Supabase setup, Vercel deploy).

```bash
npm install
cp ../.env.example .env   # keep only the `frontend/.env` section, fill in real values
npm run dev             # http://localhost:5173
```

See `CLAUDE.md` in this directory for the original detailed feature/schema spec this UI was built against (now annotated where the real backend has superseded parts of it).
