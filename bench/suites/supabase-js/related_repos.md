# Related repositories (hand-maintained, last updated 2025)

- supabase-js: the umbrella client (`createClient`). Thin wrapper that builds one client per
  Supabase service and exposes them as `supabase.auth`, `supabase.from()/rpc()`, `supabase.storage`,
  `supabase.functions` and `supabase.channel()`. Re-exports the auth and realtime APIs plus selected
  postgrest and functions types.
- postgrest-js: query builder for the REST/database API (PostgREST), including the typed
  select-query parser. Backs `from()`, `rpc()` and `schema()`.
- auth-js: the auth client (historically gotrue-js): sessions, sign-in methods, MFA, admin API.
- storage-js: Storage client: buckets and file operations (upload, download, signed URLs).
- realtime-js: websocket client for Realtime channels: broadcast, presence and Postgres changes.
- functions-js: client for invoking Edge Functions.

How they connect:
- supabase-js depends on the other five as published npm packages (`@supabase/*`), pinned in its
  package.json, not as source. A change in a library only reaches supabase-js after a release and
  a version bump.
- supabase-js derives each service URL from the project URL (`/rest/v1`, `/auth/v1`,
  `/storage/v1`, `/functions/v1`, `/realtime/v1`) and passes along the shared headers and a fetch
  wrapper that adds the API key and the current user's access token.
- Options given to `createClient` (`db`, `auth`, `realtime`, `global`, `accessToken`) are merged with
  defaults in supabase-js and forwarded to the matching library; new library options are not
  available from `createClient` until supabase-js forwards them.
- Realtime reads the current access token from the auth session; signing out resets realtime's auth.
