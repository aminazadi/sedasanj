<?php
namespace Engine\Host;

class Factory
{
    const CONFIG = '/etc/asterisk-recording-uploader/host.json';

    public static function create(): Adapter
    {
        if (!is_file(self::CONFIG)) {
            return new FreePbx();
        }
        $cfg = json_decode((string) file_get_contents(self::CONFIG), true);
        if (!is_array($cfg) || ($cfg['product'] ?? '') !== 'issabel-recuploader') {
            throw new \RuntimeException('SS-SYS-1010: Host profile is invalid; re-run activation.');
        }
        return new Issabel($cfg);
    }
}
