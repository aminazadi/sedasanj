<?php
/**
 * autoload.php - tiny PSR-4-ish autoloader for the Engine\ namespace,
 * mapping Engine\Foo\Bar -> src/Foo/Bar.php. No Composer dependency
 * assumed, since this engine is meant to run standalone on any
 * Asterisk/FreePBX/Issabel box (plan.md §3.4).
 */

require_once __DIR__ . '/src/polyfills.php';

spl_autoload_register(function (string $class) {
    $prefix = 'Engine\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($path)) {
        require $path;
    }
});
