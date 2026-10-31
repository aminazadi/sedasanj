<?php
namespace Engine\Host;

class FreePbx implements Adapter
{
    public function cdr(): array
    {
        global $amp_conf, $db, $freepbx_conf, $bootstrap_settings;
        if (!is_file('/etc/freepbx.conf')) {
            throw new \RuntimeException('SS-CDR-1001: PBX configuration is unavailable; run activation.');
        }
        require_once '/etc/freepbx.conf';
        return [\FreePBX::Cdr()->getCdrDbHandle(), \FreePBX::Config()->get('CDRDBTABLENAME') ?: 'cdr'];
    }

    public function extensions(): array
    {
        $this->cdr();
        return function_exists('core_users_list') ? core_users_list() : \FreePBX::Core()->getAllUsers();
    }
}
