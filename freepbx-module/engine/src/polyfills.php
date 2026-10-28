<?php
/**
 * polyfills.php - PHP 7.4 polyfills for the handful of PHP 8.0+ string
 * functions used for readability elsewhere in the engine. The plan's
 * target baseline is PHP 7.4 (plan.md §3.1: "no PHP 8-only syntax"), and
 * FreePBX 16 ships 7.4, so these keep the same code running unmodified on
 * both. Guarded with function_exists() so nothing changes on a PHP 8 host.
 */

if (!function_exists('str_starts_with')) {
    function str_starts_with(string $haystack, string $needle): bool
    {
        return $needle === '' || strncmp($haystack, $needle, strlen($needle)) === 0;
    }
}

if (!function_exists('str_ends_with')) {
    function str_ends_with(string $haystack, string $needle): bool
    {
        if ($needle === '') {
            return true;
        }
        $len = strlen($needle);
        return $len <= strlen($haystack) && substr_compare($haystack, $needle, -$len) === 0;
    }
}

if (!function_exists('str_contains')) {
    function str_contains(string $haystack, string $needle): bool
    {
        return $needle === '' || strpos($haystack, $needle) !== false;
    }
}
