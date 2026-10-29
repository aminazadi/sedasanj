# Help center (مرکز راهنما)

Articles, error-code explanations, images and videos managed by staff in the admin panel
(**مرکز راهنما**) and read publicly at `/help`. The FreePBX module links every failure to
`https://<site>/help/errors/<CODE>` (for example `SS-UPL-0401`).

## Data and API

- Tables (migration `0054_help_center`): `help_categories`, `help_articles` (with a generated
  full-text column), `help_error_codes` (code → article), `help_media`.
- Public: `GET /v1/help/categories|articles|articles/{slug}|errors/{code}|media/{id}`
  (rate-limited per IP). Only published articles are visible; a code whose article is a draft
  resolves but returns `article_published: false`.
- Staff: `/v1/admin/help/*`. Reading needs any staff role; every write needs `super_admin` and
  writes an `audit_events` row.
- Article HTML is rebuilt from an allowlist on every write (`app/services/help_content.py`).
  Images/videos must be platform media (`/v1/help/media/<uuid>`); iframes are limited to
  `youtube-nocookie.com/embed/...` and `aparat.com/.../embed/...` and always get a sandbox.
- Uploads are validated by magic bytes (PNG, JPEG, WebP, GIF, MP4, WebM); SVG is refused.
  Limits: 8 MB images, 120 MB videos (reverse proxy `client_max_body_size` must allow it).

## Error-code catalog

`app/data/module_error_codes.json` is exported from
`freepbx-module/engine/src/ErrorCatalog.php`; a test fails when they drift. Regenerate after
adding module codes:

```bash
docker run --rm -v "$PWD/freepbx-module/engine/src":/m:ro php:8.2-cli php -r 'require "/m/ErrorCatalog.php"; $o=[]; foreach (Engine\ErrorCatalog::ENTRIES as $c=>$e) $o[]=["code"=>$c,"severity"=>$e[0],"retryable"=>$e[1],"title"=>$e[2],"action"=>$e[3]]; echo json_encode($o, JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES),"\n";' > sedasanj/apps/api/app/data/module_error_codes.json
```

Then press **«افزودن کدهای ماژول»** in the admin page (`POST /v1/admin/help/error-codes/seed-module`);
it creates missing codes and refreshes titles without touching existing article links.

## Smoke test

`scripts/smoke_help_center.py` exercises the whole API against a disposable PostgreSQL.
Minimal schema: `CREATE ROLE cbi_app; CREATE TABLE staff_users (id uuid PRIMARY KEY DEFAULT gen_random_uuid());`
plus an `audit_events` table (see the model), then run the migration statements.
