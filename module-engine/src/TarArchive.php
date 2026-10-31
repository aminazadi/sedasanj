<?php
namespace Engine;

/* Strict ustar/gzip reader: no links, extension records, devices or extraction by a shell. */
class TarArchive
{
    public static function extract(string $archive, string $destination): void
    {
        $stream = gzopen($archive, 'rb');
        if (!$stream) { throw new \RuntimeException('SS-UPD-1010'); }
        $total = 0; $entries = 0; $seen = [];
        try {
            while (!gzeof($stream)) {
                $header = self::read($stream, 512);
                if ($header === str_repeat("\0", 512)) { break; }
                if (strlen($header) !== 512) { throw new \RuntimeException('SS-UPD-1010'); }
                $sum = 0;
                for ($i = 0; $i < 512; $i++) { $sum += ($i >= 148 && $i < 156) ? 32 : ord($header[$i]); }
                if ($sum !== octdec(trim(substr($header, 148, 8), " \0"))) { throw new \RuntimeException('SS-UPD-1010'); }
                $name = rtrim(substr($header, 0, 100), "\0");
                $prefix = rtrim(substr($header, 345, 155), "\0");
                if ($prefix !== '') { $name = $prefix . '/' . $name; }
                $name = rtrim($name, '/');
                $parts = explode('/', $name);
                $type = $header[156];
                $sizeField = trim(substr($header, 124, 12), " \0");
                if (!preg_match('/^[0-7]+$/', $sizeField)) { throw new \RuntimeException('SS-UPD-1010'); }
                $size = octdec($sizeField);
                $mode = octdec(trim(substr($header, 100, 8), " \0"));
                if (++$entries > 5000 || isset($seen[$name]) || $parts[0] !== 'recuploader'
                    || array_intersect($parts, ['', '.', '..']) || strpos($name, '\\') !== false
                    || preg_match('/[\x00-\x1f\x7f]/', $name) || !in_array($type, ["\0", '0', '5'], true)
                    || ($mode & 07000) || ($type === '5' && $size !== 0)) { throw new \RuntimeException('SS-UPD-1010'); }
                $seen[$name] = true; $total += $size;
                if ($total > 1073741824) { throw new \RuntimeException('SS-UPD-1010'); }
                $path = $destination . '/' . $name;
                $parent = $type === '5' ? $path : dirname($path);
                if (!is_dir($parent) && !mkdir($parent, 0755, true)) { throw new \RuntimeException('SS-SYS-1007'); }
                if ($type !== '5') {
                    $file = fopen($path, 'xb');
                    if (!$file) { throw new \RuntimeException('SS-UPD-1010'); }
                    try {
                        for ($remaining = $size; $remaining > 0;) {
                            $chunk = self::read($stream, min(65536, $remaining));
                            if ($chunk === '' || fwrite($file, $chunk) !== strlen($chunk)) { throw new \RuntimeException('SS-UPD-1010'); }
                            $remaining -= strlen($chunk);
                        }
                    } finally { fclose($file); }
                    chmod($path, ($mode & 0111) ? 0755 : 0644);
                    $padding = (512 - ($size % 512)) % 512;
                    if ($padding) { self::read($stream, $padding); }
                }
            }
            if (!isset($seen['recuploader/module.xml'])) { throw new \RuntimeException('SS-UPD-1010'); }
        } finally { gzclose($stream); }
    }

    private static function read($stream, int $size): string
    {
        $data = '';
        while (strlen($data) < $size && !gzeof($stream)) {
            $chunk = gzread($stream, $size - strlen($data));
            if ($chunk === false || $chunk === '') { break; }
            $data .= $chunk;
        }
        if (strlen($data) !== $size) { throw new \RuntimeException('SS-UPD-1010'); }
        return $data;
    }
}
