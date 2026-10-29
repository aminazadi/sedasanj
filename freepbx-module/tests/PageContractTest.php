<?php

$page = file_get_contents(__DIR__ . '/../page.recuploader.php');
if (strpos($page, "url.searchParams.set('tab', name)") === false
    || strpos($page, "$('a[href=\"#tab-' + requestedTab + '\"]').tab('show')") === false
    || strpos($page, "$('#recuploader-form').on('submit'") === false) {
    throw new RuntimeException('Active-tab URL persistence contract is missing.');
}

foreach (array('id="tab-health"', "'health'", 'sj-activation-cmd', 'name="sj_csrf"', "sjCall('installdep'") as $marker) {
    if (strpos($page, $marker) === false) {
        throw new RuntimeException("Page is missing {$marker}.");
    }
}
// Every AJAX command the page calls must be authenticated by the BMO class.
$class = file_get_contents(__DIR__ . '/../Recuploader.class.php');
preg_match_all("/sjCall\\('([a-z]+)'/", $page, $calls);
foreach (array_unique($calls[1]) as $command) {
    if (strpos($class, "'" . $command . "'") === false) {
        throw new RuntimeException("AJAX command {$command} is not handled or authenticated in Recuploader.class.php.");
    }
}

// The page's progress list must match the root helper's steps one to one.
$helper = file_get_contents(__DIR__ . '/../bin/sedasanj-recuploader-update.sh');
preg_match('/^STEPS=\\(([^)]*)\\)/m', $helper, $steps);
preg_match_all("/\\['([a-z]+)', '/", substr($page, strpos($page, 'var sjSteps')), $labels);
$pageSteps = array_slice($labels[1], 0, count(preg_split('/\\s+/', trim($steps[1]))));
if ($pageSteps !== preg_split('/\\s+/', trim($steps[1]))) {
    throw new RuntimeException('Update steps differ between the helper (' . $steps[1] . ') and the page (' . implode(' ', $pageSteps) . ').');
}

echo "FreePBX page contract passed.\n";
