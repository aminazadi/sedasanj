<?php
namespace {
    class FreePBX_Helpers {}
    interface BMO {}
}
namespace FreePBX\modules {
    function extension_loaded($extension) {
        return !in_array($extension, $GLOBALS['missing_extensions'], true);
    }
}
namespace {
    require __DIR__ . '/../Recuploader.class.php';
    class RuntimeRequirementsProbe extends \FreePBX\modules\Recuploader {
        public function __construct() {}
        public function check() { $this->assertRuntimeRequirements(); }
    }
    $probe = new RuntimeRequirementsProbe();
    $GLOBALS['missing_extensions'] = array();
    $probe->check();
    foreach (array('curl', 'zlib', 'json', 'simplexml') as $extension) {
        $GLOBALS['missing_extensions'] = array($extension);
        try {
            $probe->check();
            throw new \Exception('Missing extension was accepted: ' . $extension);
        } catch (\RuntimeException $error) {
            if (strpos($error->getMessage(), 'SS-DEP-1002:') !== 0
                || strpos($error->getMessage(), $extension) === false
                || strpos($error->getMessage(), 'retry') === false) {
                throw new \Exception('Missing extension needs a coded, actionable error');
            }
        }
    }
    echo "Runtime requirements passed.\n";
}
