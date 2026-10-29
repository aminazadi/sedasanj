---
name: freepbx-php-compat
description: Keep FreePBX module PHP compatible with PHP 5.6 (FreePBX 15 web layer) and 7.4 (engine and FreePBX 16). Use for any edit to .php files under freepbx-module/.
---

# PHP compatibility

## Layers (plan, section 2)

- **Web layer** (`freepbx-module/Recuploader.class.php`, `page.recuploader.php`) runs in FreePBX's web PHP: 5.6 on FreePBX 15 base, 7.4 on 16, 8.2 on 17. Today both layers need ≥ 7.4 (typed properties, `fn`, `??`, `\Throwable`); FreePBX 15 support (Tier 2) means rewriting the web layer to 5.6 syntax.
- **Engine** (`freepbx-module/engine/`) runs in PHP CLI and may use a configurable `php_binary` ≥ 7.4. `engine/src/polyfills.php` polyfills `str_starts_with`, `str_ends_with` and `str_contains`, so those three are allowed in engine code.

## Forbidden in engine code (7.4 target)

`match`, nullsafe `?->`, named arguments, constructor property promotion, union types, attributes, `mixed`, `static` return type, enums, readonly.

## Additionally forbidden in web-layer code (5.6 target)

`??`, `<=>`, scalar type hints and return types, `\Throwable` (catch `\Exception`), `fn`, typed properties, `...` in calls if targeting < 5.6, short `[]` is fine from 5.4, `random_bytes` (use polyfill or `openssl_random_pseudo_bytes`), `intdiv`.

## Extensions

`curl`, `zlib`, `json`, `simplexml`; `sodium` (updater signature verification; fallback to a bundled `sodium_compat` or a coded error is planned); `pdo_sqlite` for the CLI queue backend; `ctype`.

## How to verify

```bash
php -l path/to/file.php   # run under each supported PHP, via containers; PHP is not installed on the maintainer's Mac
```

Run `freepbx-module/tests/*` under 7.4 and 8.2 at least. Do not claim 5.6 compatibility unless the web-layer files were linted with 5.6 (⚠ lab).
