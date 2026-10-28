<?php

$page = file_get_contents(__DIR__ . '/../page.recuploader.php');
if (strpos($page, "url.searchParams.set('tab', name)") === false
    || strpos($page, "$('a[href=\"#tab-' + requestedTab + '\"]').tab('show')") === false
    || strpos($page, "$('#recuploader-form').on('submit'") === false) {
    throw new RuntimeException('Active-tab URL persistence contract is missing.');
}

echo "FreePBX page contract passed.\n";
