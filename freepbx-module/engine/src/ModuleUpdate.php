<?php

namespace Engine;

class ModuleUpdateError extends \RuntimeException
{
}

/**
 * Host-agnostic pieces of the module self-update flow: ingest URL
 * derivation and release artifact verification. Kept free of FreePBX
 * classes so tests/ModuleUpdateTest.php can exercise it standalone.
 *
 * Release signatures are detached Ed25519 signatures (base64) over the
 * lowercase ASCII sha256 hex digest of the release zip; the public key
 * file holds the raw 32-byte key, base64-encoded, optionally preceded by
 * '#' comment lines.
 */
class ModuleUpdate
{
    const MAX_ARTIFACT_BYTES = 209715200; // 200 MiB

    /**
     * Swaps the trailing /calls of the configured ingest endpoint for
     * $path, the same way Uploader derives /voicemails.
     */
    public static function endpointFor(string $endpoint, string $path): string
    {
        $url = preg_replace('#/calls/?$#', $path, $endpoint);
        if (!is_string($url) || $url === $endpoint) {
            throw new ModuleUpdateError('Endpoint must end with /v1/ingest/calls');
        }
        return $url;
    }

    public static function updatesUrl(string $endpoint, array $query): string
    {
        return self::endpointFor($endpoint, '/module/updates') . '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986);
    }

    public static function releasesUrl(string $endpoint): string
    {
        return self::endpointFor($endpoint, '/module/releases');
    }

    public static function downloadUrl(string $endpoint, string $releaseId): string
    {
        if (!self::isReleaseId($releaseId)) {
            throw new ModuleUpdateError('Invalid release id');
        }
        return self::endpointFor($endpoint, '/module/releases/' . rawurlencode($releaseId) . '/download');
    }

    public static function reportUrl(string $endpoint): string
    {
        return self::endpointFor($endpoint, '/module/update-report');
    }

    public static function isJobId(string $value): bool
    {
        return (bool) preg_match('/^[a-f0-9]{32}$/', $value);
    }

    public static function isReleaseId(string $value): bool
    {
        return (bool) preg_match('/^[A-Za-z0-9_-]{1,64}$/', $value);
    }

    public static function isVersion(string $value): bool
    {
        return (bool) preg_match('/^\d+\.\d+\.\d+$/', $value);
    }

    /** Returns the raw 32-byte key, or null when the file is a placeholder or malformed. */
    public static function parsePublicKey(string $text): ?string
    {
        $lines = array();
        foreach (preg_split('/\r?\n/', $text) as $line) {
            $line = trim($line);
            if ($line !== '' && $line[0] !== '#') {
                $lines[] = $line;
            }
        }
        if (count($lines) !== 1) {
            return null;
        }
        $raw = base64_decode($lines[0], true);
        if ($raw === false || strlen($raw) !== 32) {
            return null;
        }
        return $raw;
    }

    public static function verifySignature(string $sha256Hex, string $signatureB64, string $publicKey): bool
    {
        if (!function_exists('sodium_crypto_sign_verify_detached')
            || !preg_match('/^[a-f0-9]{64}$/', $sha256Hex)
            || strlen($publicKey) !== 32) {
            return false;
        }
        $signature = base64_decode($signatureB64, true);
        if ($signature === false || strlen($signature) !== 64) {
            return false;
        }
        try {
            return sodium_crypto_sign_verify_detached($signature, $sha256Hex, $publicKey);
        } catch (\Throwable $exc) {
            return false;
        }
    }

    /**
     * Checks a downloaded artifact against the release metadata. Throws a
     * ModuleUpdateError naming the first failed check.
     */
    public static function verifyArtifact(string $path, array $release, string $publicKey): void
    {
        $size = @filesize($path);
        if ($size === false || $size <= 0 || $size > self::MAX_ARTIFACT_BYTES) {
            throw new ModuleUpdateError('Downloaded release has an invalid size');
        }
        if (isset($release['size']) && (int) $release['size'] > 0 && (int) $release['size'] !== $size) {
            throw new ModuleUpdateError('Downloaded release size does not match');
        }
        $expected = strtolower((string) ($release['sha256'] ?? ''));
        $actual = hash_file('sha256', $path);
        if ($actual === false || !hash_equals($expected, $actual)) {
            throw new ModuleUpdateError('Downloaded release checksum does not match');
        }
        if (!self::verifySignature($actual, (string) ($release['signature'] ?? ''), $publicKey)) {
            throw new ModuleUpdateError('Release signature verification failed');
        }
    }
}
