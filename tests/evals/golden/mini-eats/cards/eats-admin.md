# eats-admin
> Restaurant-owner dashboard for eats: menus, orders, payouts.
`./eats-admin` · typescript, nextjs, react, drizzle, neon · HEAD <sha>
app: `./eats-admin/eats-admin`

## Relates
→ shared-ui: uses package npm:@eats/ui (extracted · eats-admin/package.json:10)
→ shared-ui: references path shared-ui/src (extracted · eats-admin/tsconfig.json:1)
→ eats: shares tables cook_profiles, listings (extracted · eats-admin/lib/admin-queries.ts:3)
← eats: docs mention (inferred · eats/CLAUDE.md:3)
→ eats: docs mention (inferred · eats-admin/README.md:3)

## Run
dev `cd eats-admin && npm run dev`
build `cd eats-admin && npm run build`

## Layout
eats-admin/db/ → database
eats-admin/lib/ → library code

## Exposes
db table platform_discounts
package npm:eats-admin
