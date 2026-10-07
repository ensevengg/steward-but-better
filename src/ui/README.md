# Steward review workspace

From this directory run `npm ci`, `npm run build`, then `npm start`. The FastAPI
backend must also be running; `BRAIN_SERVICE_URL` defaults to `http://127.0.0.1:8000`.
Set it in the launch environment or `.env.local` when using another address.

The UI proxies durable backend state. It does not own JSON files or generate
judgments. Polling is sequential and abortable, stale values are labelled, and
case closure uses optimistic version checks. Mobile tabs separate timing from
case review; motion is minimal and honours reduced-motion preferences.

`npm run typecheck`, `npm run lint`, and `npm run build` validate the application.
See the [root README](../../README.md) for the recorded study, API changes,
browser test, model setup and known limitations.
