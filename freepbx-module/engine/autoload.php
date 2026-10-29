<?php
/**
 * autoload.php - tiny PSR-4-ish autoloader for the Engine\ namespace,
 * mapping Engine\Foo\Bar -> src/Foo/Bar.php. No Composer dependency
 * assumed, since this engine is meant to run standalone on any
 * Asterisk/FreePBX/Issabel box (plan.md §3.4).
 *
 * Helper classes that live in a file named after another class (an exception
 * declared next to the class that throws it) cannot be found by name alone, so
 * they are listed in the class map. Without it, throwing e.g. UploadError from
 * Staging before Uploader.php was loaded died with "Class not found".
 */

require_once __DIR__ . '/src/polyfills.php';

spl_autoload_register(function (string $class) {
    static $classMap = [
        'Engine\\UploadError' => 'Uploader.php',
        'Engine\\StagingError' => 'Staging.php',
        'Engine\\ConfigError' => 'Config.php',
        'Engine\\ConfigProfileError' => 'ConfigProfile.php',
        'Engine\\ModuleUpdateError' => 'ModuleUpdate.php',
        'Engine\\StateStoreInterface' => 'StateStore.php',
        'Engine\\SqliteStateStore' => 'StateStore.php',
        'Engine\\JsonStateStore' => 'StateStore.php',
        'Engine\\QueueInterface' => 'Queue.php',
        'Engine\\SqliteQueue' => 'Queue.php',
        'Engine\\JsonQueue' => 'Queue.php',
        'Engine\\Audio\\WavError' => 'Audio/Wav.php',
        'Engine\\Audio\\WavFile' => 'Audio/Wav.php',
    ];
    if (isset($classMap[$class])) {
        require_once __DIR__ . '/src/' . $classMap[$class];
        return;
    }
    $prefix = 'Engine\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($path)) {
        require_once $path;
    }
});
