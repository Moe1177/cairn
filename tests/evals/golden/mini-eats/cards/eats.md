# eats
> Consumer marketplace app where customers order home-cooked meals from local cooks.
`./eats` · typescript, nextjs, react, drizzle, neon · HEAD <sha>
app: `./eats/my-app`

## Relates
→ shared-ui: uses package npm:@eats/ui (extracted · my-app/package.json:10)
→ eats-admin: shares tables cook_profiles, listings (extracted · eats-admin/eats-admin/lib/admin-queries.ts:3)
→ eats-admin: docs mention (inferred · CLAUDE.md:3)
← eats-admin: docs mention (inferred · eats-admin/eats-admin/README.md:3)

## Run
dev `cd my-app && npm run dev`
build `cd my-app && npm run build`
test `cd my-app && npm run test`

## Layout
my-app/db/ → database
my-app/lib/ → library code

## Exposes
db table cook_profiles
db table listings
db table orders
db table users
package npm:my-app

## Notes
Production app; deploys on Vercel.
