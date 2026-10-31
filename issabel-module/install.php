<?php
if (!defined('ISSABELPBX_IS_AUTH')) { die('No direct script access allowed'); }
if (version_compare(PHP_VERSION, '5.4.0', '<')) { return false; }
// Installation through the GUI intentionally requires a separate root activation.
return true;
