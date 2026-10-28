<?php
/**
 * Seda Sanj - admin settings page (sedasanj.ir).
 * Loaded by the FreePBX framework when the user visits
 * Admin > Seda Sanj (display=recuploader).
 */

if (!defined('FREEPBX_IS_AUTH')) {
	die('No direct script access allowed');
}

$recuploader = \FreePBX::Recuploader();
$s           = $recuploader->getSettings();
$saved       = isset($_REQUEST['recuploader_save']);
$saveError   = $saved ? $recuploader->getLastSaveError() : null;
$importPreview = $recuploader->getImportPreview();
$importMessage = $recuploader->getImportMessage();
$queueSummary = $recuploader->getQueueSummary();
$voicemailSummary = $recuploader->getVoicemailSummary();
$missedCallSummary = $recuploader->getMissedCallSummary();
$pageError = $recuploader->getLastSaveError();
$serviceStatus = $recuploader->getServiceStatus();
$moduleVersion = $recuploader->getModuleVersion();
$logoSvg = @file_get_contents(__DIR__ . '/assets/images/sedasanj-logo.svg');

$logLevels   = array('DEBUG', 'INFO', 'WARNING', 'ERROR');
$logMinLevel = (isset($_REQUEST['log_min_level']) && in_array($_REQUEST['log_min_level'], $logLevels, true))
	? $_REQUEST['log_min_level']
	: 'INFO';
$logMaxLines = isset($_REQUEST['log_max_lines']) ? max(10, min(2000, (int) $_REQUEST['log_max_lines'])) : 200;
$logLines    = $recuploader->readLogLines($logMinLevel, $logMaxLines);

/**
 * Renders a FreePBX-style inline help popover icon.
 * The popover itself is initialised in the page's <script> block at the
 * bottom (see the "Initialize help popovers" section) - FreePBX's admin
 * chrome does not reliably auto-init popovers for custom modules.
 */
$helpIcon = function ($title, $content) {
	return '<i class="fa fa-question-circle fpbx-help-icon"'
		. ' data-toggle="popover" data-trigger="hover" data-placement="top"'
		. ' data-html="true"'
		. ' data-content="' . htmlspecialchars($content, ENT_QUOTES, 'UTF-8') . '"'
		. ' data-original-title="' . htmlspecialchars($title, ENT_QUOTES, 'UTF-8') . '"></i>';
};
?>
<style>
	/* Mirrors the Seda Sanj client panel (sedasanj/web/client/src/index.css):
	 * square corners, no shadows, dotted green chrome, beige-bordered cards. */
	@font-face { font-family: "SedaSanj Vazirmatn"; src: url("modules/recuploader/assets/fonts/Vazirmatn-Variable.woff2") format("woff2-variations"); font-weight: 100 900; font-style: normal; font-display: swap; }
	.sedasanj-panel { --sj-green: #4b6e48; --sj-green-dark: #3d5b3a; --sj-sand: #b2ac88; --sj-canvas: #f2f0ef; --sj-neutral: #898989; --sj-ink: #0f172a; --sj-label: #475569; --sj-dots-light: radial-gradient(circle, rgb(242 240 239 / 0.1) 0 1px, transparent 1.15px) 0 0 / 7px 7px; --sj-dots-grey: radial-gradient(circle, rgb(137 137 137 / 0.14) 0 1px, transparent 1.15px) 0 0 / 7px 7px; margin: 0 -15px; padding: 24px 24px 32px; min-height: 100vh; background: var(--sj-canvas); color: var(--sj-neutral); font-family: "SedaSanj Vazirmatn", Vazirmatn, system-ui, -apple-system, "Segoe UI", sans-serif; }
	.sedasanj-panel *, .sedasanj-panel *::before, .sedasanj-panel *::after { border-radius: 0 !important; box-shadow: none !important; }
	.sedasanj-panel h1, .sedasanj-panel h3, .sedasanj-panel h4 { font-family: inherit; color: var(--sj-ink); }
	.sedasanj-panel a { color: var(--sj-green); }

	/* ---- Brand header (the panel sidebar's dotted green) ---- */
	.sedasanj-panel .sj-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; margin-bottom: 16px; padding: 22px 28px; background: var(--sj-green) var(--sj-dots-light); border: 1px solid var(--sj-green); color: var(--sj-canvas); }
	.sedasanj-panel .sj-brand { display: flex; align-items: center; gap: 24px; }
	.sedasanj-panel .sj-logo { display: block; width: 144px; color: var(--sj-canvas); line-height: 0; }
	.sedasanj-panel .sj-logo svg { width: 100%; height: auto; }
	.sedasanj-panel .sj-brand-text { padding-left: 24px; border-left: 1px solid var(--sj-sand); }
	.sedasanj-panel .sj-brand-text h1 { margin: 0; font-size: 20px; font-weight: 900; color: var(--sj-canvas); }
	.sedasanj-panel .sj-brand-text p { margin: 4px 0 0; color: var(--sj-sand); font-size: 13px; }
	.sedasanj-panel .sj-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.sedasanj-panel .sj-pill { display: inline-flex; align-items: center; gap: 10px; padding: 7px 14px; font-size: 12px; line-height: 1.4; font-weight: 700; border: 1px solid var(--sj-sand); background: var(--sj-canvas); color: #000; }
	.sedasanj-panel .sj-pill.sj-version { background: var(--sj-sand); }
	.sedasanj-panel .sj-dot { position: relative; flex: 0 0 auto; width: 10px; height: 10px; background: var(--sj-neutral); }
	.sedasanj-panel .sj-dot::after { position: absolute; inset: -2px; border: 1px solid currentColor; content: ""; opacity: 0; pointer-events: none; animation: sj-dot-pulse 1.9s ease-out infinite; }
	.sedasanj-panel .sj-pill.is-running .sj-dot { background: var(--sj-green); color: var(--sj-green); }
	.sedasanj-panel .sj-pill.is-stopped .sj-dot { color: #dc2626; }
	@keyframes sj-dot-pulse { 0% { opacity: .9; transform: scale(1); } 100% { opacity: 0; transform: scale(2.2); } }
	@media (prefers-reduced-motion: reduce) { .sedasanj-panel .sj-dot::after { animation: none; } }
	.sedasanj-panel .sj-pill.is-stopped { color: #b91c1c; }
	.sedasanj-panel .sj-pill.is-stopped .sj-dot { background: #dc2626; }

	/* ---- Main card ---- */
	.sedasanj-panel .sj-card { background: var(--sj-canvas); border: 1px solid var(--sj-sand); }
	.sedasanj-panel .sj-card > .nav-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 0; padding: 10px 12px; background: var(--sj-green) var(--sj-dots-light); border-bottom: 1px solid var(--sj-sand); }
	.sedasanj-panel .sj-card > .nav-tabs > li { float: none; margin: 0; }
	.sedasanj-panel .sj-card > .nav-tabs > li > a { display: flex; align-items: center; gap: 8px; margin: 0; padding: 9px 12px; border: 0; color: var(--sj-canvas); font-size: 13px; background: transparent; transition: background-color .2s, color .2s; }
	.sedasanj-panel .sj-card > .nav-tabs > li > a .fa { color: var(--sj-sand); font-size: 15px; transition: color .2s; }
	.sedasanj-panel .sj-card > .nav-tabs > li > a:hover,
	.sedasanj-panel .sj-card > .nav-tabs > li.active > a,
	.sedasanj-panel .sj-card > .nav-tabs > li.active > a:hover,
	.sedasanj-panel .sj-card > .nav-tabs > li.active > a:focus { border: 0; background: var(--sj-canvas); color: var(--sj-green); }
	.sedasanj-panel .sj-card > .nav-tabs > li.active > a { font-weight: 700; }
	.sedasanj-panel .sj-card > .nav-tabs > li > a:hover .fa,
	.sedasanj-panel .sj-card > .nav-tabs > li.active > a .fa { color: var(--sj-green); }
	.sedasanj-panel .sj-card > .nav-tabs > li > a:focus { outline: none; }
	.sedasanj-panel .sj-card > .nav-tabs > li > a:focus-visible { outline: 2px solid var(--sj-sand); outline-offset: -2px; }
	.sedasanj-panel .sj-card > .tab-content { padding: 28px 24px 8px; background: #fff; }

	/* ---- Forms ---- */
	.sedasanj-panel .control-label { color: var(--sj-label); font-weight: 500; font-size: 13px; }
	.sedasanj-panel .form-control { height: 38px; border: 1px solid var(--sj-sand); background-color: var(--sj-canvas); color: var(--sj-ink); font-family: inherit; transition: border-color .15s; }
	.sedasanj-panel .form-control:focus { border-color: var(--sj-green); outline: none; }
	.sedasanj-panel .form-control::placeholder { color: #a8a8a8; }
	.sedasanj-panel select.form-control { appearance: none; -webkit-appearance: none; padding-right: 36px; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20' fill='none'%3E%3Cpath d='m5 7.5 5 5 5-5' stroke='%23898989' stroke-width='1.5' stroke-linecap='square' stroke-linejoin='miter'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 10px center; background-size: 18px; }
	.sedasanj-panel .sj-log-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; margin-bottom: 16px; }
	.sedasanj-panel .sj-log-field { display: flex; align-items: center; gap: 10px; }
	.sedasanj-panel .sj-log-field label { margin: 0; color: var(--sj-label); font-size: 13px; font-weight: 500; white-space: nowrap; }
	.sedasanj-panel #log_min_level { width: 140px; }
	.sedasanj-panel #log_max_lines { width: 110px; }
	.sedasanj-panel input[type="file"].form-control { height: auto; padding: 7px 10px; }
	.sedasanj-panel .help-block { color: #64748b; font-size: 12px; }
	.sedasanj-panel .fpbx-help-icon { color: var(--sj-sand); }
	.sedasanj-panel .switch input:checked + .slider { background-color: var(--sj-green); }
	.sedasanj-panel .btn { border: 1px solid var(--sj-neutral); background: transparent; color: var(--sj-green); font-family: inherit; font-weight: 500; transition: background-color .15s; }
	.sedasanj-panel .btn:hover, .sedasanj-panel .btn:focus { background: #f1f5f9; color: var(--sj-green); }
	.sedasanj-panel .btn-primary, .sedasanj-panel .btn-sj { border-color: var(--sj-green); background: var(--sj-green); color: var(--sj-canvas); }
	.sedasanj-panel .btn-primary:hover, .sedasanj-panel .btn-primary:focus, .sedasanj-panel .btn-sj:hover, .sedasanj-panel .btn-sj:focus { border-color: var(--sj-green-dark); background: var(--sj-green-dark); color: var(--sj-canvas); }
	.sedasanj-panel .btn-sj { padding: 9px 22px; font-weight: 700; }
	.sedasanj-panel .sj-actions { margin: 0; padding: 16px 24px; background: var(--sj-canvas) var(--sj-dots-grey); border-top: 1px solid var(--sj-sand); }
	.sedasanj-panel hr { border-top-color: var(--sj-sand); }

	/* ---- Alerts ---- */
	.sedasanj-panel .alert { border: 1px solid var(--sj-sand); background: var(--sj-canvas); color: #334155; }
	.sedasanj-panel .alert-info { border-inline-start: 3px solid var(--sj-sand); }
	.sedasanj-panel .alert-success { border-color: #b7c9b5; border-inline-start: 3px solid var(--sj-green); background: #eef3ed; color: var(--sj-green-dark); }
	.sedasanj-panel .alert-warning { border-color: #e2d6a8; border-inline-start: 3px solid #b8932f; background: #fbf7ea; color: #6b5414; }
	.sedasanj-panel .alert-danger { border-color: #efc9c9; border-inline-start: 3px solid #dc2626; background: #fdf2f2; color: #991b1b; }

	/* ---- Stat cards (panel-stat-card) ---- */
	.sedasanj-panel .sj-stats { margin: 0 -8px 18px; }
	.sedasanj-panel .sj-stats > [class*="col-"] { padding: 0 8px; }
	.sedasanj-panel .sj-stat { position: relative; margin-bottom: 12px; padding: 14px 16px; border: 1px solid var(--sj-sand); background: radial-gradient(circle at 2.75rem 2.75rem, #f2f0ef 0 2.5rem, rgb(242 240 239 / 0.94) 3rem, rgb(242 240 239 / 0.78) 4rem, rgb(242 240 239 / 0.52) 5rem, rgb(242 240 239 / 0.24) 6rem, transparent 7rem), var(--sj-dots-grey), var(--sj-canvas); transition: border-color .15s; }
	.sedasanj-panel .sj-stat:hover { border-color: var(--sj-neutral); }
	.sedasanj-panel .sj-stat span { display: block; margin-bottom: 4px; color: var(--sj-label); font-size: 13px; font-weight: 500; }
	.sedasanj-panel .sj-stat strong { display: block; color: var(--sj-ink); font-size: 24px; font-weight: 800; line-height: 1.3; letter-spacing: -.02em; }

	/* ---- Tables, code, logs ---- */
	.sedasanj-panel .table > tbody > tr > th, .sedasanj-panel .table > tbody > tr > td { border-top-color: #e2e8f0; }
	.sedasanj-panel .table-striped > tbody > tr:nth-of-type(odd) { background: rgb(242 240 239 / 0.6); }
	.sedasanj-panel code { border: 1px solid rgb(178 172 136 / 0.75); background: rgb(242 240 239 / 0.75); padding: 1px 5px; color: #334155; font-size: .85em; }
	.sedasanj-panel .sj-log { max-height: 500px; overflow: auto; margin: 0 0 10px; padding: 12px; border: 1px solid var(--sj-sand); background: #1e293b; color: var(--sj-canvas); font-size: 12px; line-height: 1.6; }

	/* ---- Service information & footer ---- */
	.sedasanj-panel .sj-info { margin-top: 20px; }
	.sedasanj-panel .sj-info .panel-heading { padding: 12px 16px; background: var(--sj-canvas) var(--sj-dots-grey); border-bottom: 1px solid var(--sj-sand); }
	.sedasanj-panel .sj-info .panel-title { color: var(--sj-ink); font-size: 14px; font-weight: 700; }
	.sedasanj-panel .sj-info .panel-title .fa { color: var(--sj-green); }
	.sedasanj-panel .sj-info .panel-body { background: #fff; }
	.sedasanj-panel .sj-info dt { color: var(--sj-label); font-weight: 500; }
	.sedasanj-panel .sj-footer { display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 24px; color: var(--sj-neutral); font-size: 12px; }
	.sedasanj-panel .sj-footer .sj-logo { width: 54px; color: var(--sj-neutral); }

	@media (max-width: 767px) {
		.sedasanj-panel { padding: 16px; }
		.sedasanj-panel .sj-hero { padding: 18px; }
		.sedasanj-panel .sj-brand { flex-direction: column; align-items: flex-start; gap: 12px; }
		.sedasanj-panel .sj-brand-text { padding-left: 0; border-left: 0; }
	}
</style>

<div class="container-fluid sedasanj-panel">

	<header class="sj-hero">
		<div class="sj-brand">
			<?php if ($logoSvg !== false): ?>
				<a class="sj-logo" href="https://sedasanj.ir" target="_blank" rel="noopener" title="sedasanj.ir"><?php echo $logoSvg; ?></a>
			<?php endif; ?>
			<div class="sj-brand-text">
				<h1><?php echo _("Seda Sanj"); ?></h1>
				<p><?php echo _("Call recording uploader &amp; AI transcription for FreePBX"); ?></p>
			</div>
		</div>
		<div class="sj-meta">
			<span class="sj-pill <?php echo $serviceStatus === 'running' ? 'is-running' : 'is-stopped'; ?>">
				<span class="sj-dot"></span>
				<?php echo $serviceStatus === 'running' ? _("Service running") : _("Service stopped"); ?>
			</span>
			<?php if ($moduleVersion['files'] !== ''): ?>
				<span class="sj-pill sj-version" title="<?php echo htmlspecialchars($moduleVersion['installed'] !== '' && $moduleVersion['installed'] !== $moduleVersion['files'] ? sprintf(_('Files are v%1$s, FreePBX has v%2$s registered - run fwconsole ma install recuploader'), $moduleVersion['files'], $moduleVersion['installed']) : _('Installed module version'), ENT_QUOTES, 'UTF-8'); ?>">v<?php echo htmlspecialchars($moduleVersion['files'], ENT_QUOTES, 'UTF-8'); ?><?php if ($moduleVersion['installed'] !== '' && $moduleVersion['installed'] !== $moduleVersion['files']): ?> <i class="fa fa-exclamation-triangle"></i><?php endif; ?></span>
			<?php endif; ?>
		</div>
	</header>

	<?php if ($saved && $saveError === null): ?>
		<div class="alert alert-success alert-dismissible" role="alert">
			<button type="button" class="close" data-dismiss="alert" aria-label="<?php echo htmlspecialchars(_('Close'), ENT_QUOTES, 'UTF-8'); ?>">
				<span aria-hidden="true">&times;</span>
			</button>
			<strong><?php echo _("Settings saved."); ?></strong>
			<?php echo _("The configuration file was regenerated and the uploader service was restarted."); ?>
		</div>
	<?php elseif ($saved && $saveError !== null): ?>
		<div class="alert alert-danger alert-dismissible" role="alert">
			<button type="button" class="close" data-dismiss="alert" aria-label="<?php echo htmlspecialchars(_('Close'), ENT_QUOTES, 'UTF-8'); ?>">
				<span aria-hidden="true">&times;</span>
			</button>
			<strong><?php echo _("Settings NOT saved."); ?></strong>
			<?php echo htmlspecialchars($saveError, ENT_QUOTES, 'UTF-8'); ?>
			<?php echo _(" The service was left running on its previous configuration."); ?>
		</div>
	<?php endif; ?>
	<?php if ($importMessage !== null): ?>
		<div class="alert alert-success"><?php echo htmlspecialchars($importMessage, ENT_QUOTES, 'UTF-8'); ?></div>
	<?php elseif (!$saved && $pageError !== null): ?>
		<div class="alert alert-danger"><?php echo htmlspecialchars($pageError, ENT_QUOTES, 'UTF-8'); ?></div>
	<?php endif; ?>

	<form method="post" action="config.php?display=recuploader" id="recuploader-form" class="form-horizontal" enctype="multipart/form-data">
		<input type="hidden" name="display" value="recuploader">

		<div class="sj-card">
		<!-- ================= Tab navigation ================= -->
		<ul class="nav nav-tabs" role="tablist">
			<li role="presentation" class="active">
				<a href="#tab-endpoint" aria-controls="tab-endpoint" role="tab" data-toggle="tab">
					<i class="fa fa-cloud-upload"></i> <?php echo _("Upload Endpoint"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-import" aria-controls="tab-import" role="tab" data-toggle="tab">
					<i class="fa fa-upload"></i> <?php echo _("Import Configuration"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-watcher" aria-controls="tab-watcher" role="tab" data-toggle="tab">
					<i class="fa fa-eye"></i> <?php echo _("Recording Watcher"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-missed-calls" aria-controls="tab-missed-calls" role="tab" data-toggle="tab">
					<i class="fa fa-phone"></i> <?php echo _("Missed Calls"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-voicemail" aria-controls="tab-voicemail" role="tab" data-toggle="tab">
					<i class="fa fa-envelope"></i> <?php echo _("Voicemail"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-post" aria-controls="tab-post" role="tab" data-toggle="tab">
					<i class="fa fa-check-circle"></i> <?php echo _("Post-Upload &amp; Archive"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-retry" aria-controls="tab-retry" role="tab" data-toggle="tab">
					<i class="fa fa-refresh"></i> <?php echo _("Retry Queue &amp; Sweeper"); ?>
				</a>
			</li>
			<li role="presentation">
				<a href="#tab-logging" aria-controls="tab-logging" role="tab" data-toggle="tab">
					<i class="fa fa-list-alt"></i> <?php echo _("Logging"); ?>
				</a>
			</li>
		</ul>

		<div class="tab-content">
			<div role="tabpanel" class="tab-pane" id="tab-import">
				<div class="alert alert-info"><?php echo _("Upload the versioned sedasanj-freepbx-config.json file. The file is validated locally and online before a masked preview is shown. Applying a preview replaces all supported settings and rolls back if the service cannot restart."); ?></div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="config_profile"><?php echo _("Configuration JSON"); ?></label>
					<div class="col-sm-6">
						<input type="hidden" name="MAX_FILE_SIZE" value="65536">
						<input type="file" class="form-control" id="config_profile" name="config_profile" accept="application/json,.json">
						<span class="help-block"><?php echo _("Maximum size: 64 KiB. Secrets are never rendered back into this page."); ?></span>
						<button type="submit" name="recuploader_import_preview" value="1" class="btn btn-default"><i class="fa fa-search"></i> <?php echo _("Validate & Preview"); ?></button>
					</div>
				</div>
				<?php if (is_array($importPreview)): ?>
					<hr>
					<h4><?php echo _("Validated Preview"); ?></h4>
					<div class="table-responsive"><table class="table table-striped table-condensed"><tbody>
					<?php foreach ($importPreview['settings'] as $key => $value): ?>
						<tr><th><?php echo htmlspecialchars($key, ENT_QUOTES, 'UTF-8'); ?></th><td><code><?php echo htmlspecialchars((string) $value, ENT_QUOTES, 'UTF-8'); ?></code></td></tr>
					<?php endforeach; ?>
					</tbody></table></div>
					<p><?php echo _("Tenant"); ?>: <strong><?php echo htmlspecialchars($importPreview['remote']['tenant'], ENT_QUOTES, 'UTF-8'); ?></strong> &middot; <?php echo _("Transport"); ?>: <strong><?php echo htmlspecialchars($importPreview['remote']['archive_format'], ENT_QUOTES, 'UTF-8'); ?></strong></p>
					<input type="hidden" name="import_token" value="<?php echo htmlspecialchars($importPreview['token'], ENT_QUOTES, 'UTF-8'); ?>">
					<button type="submit" name="recuploader_import_apply" value="1" class="btn btn-primary"><i class="fa fa-check"></i> <?php echo _("Apply Configuration"); ?></button>
				<?php endif; ?>
			</div>

			<!-- ================= Upload Endpoint ================= -->
			<div role="tabpanel" class="tab-pane active" id="tab-endpoint">

				<div class="form-group">
					<label class="col-sm-3 control-label" for="endpoint"><?php echo _("Endpoint URL"); ?></label>
					<div class="col-sm-6">
						<input type="text" class="form-control" id="endpoint" name="endpoint"
							value="<?php echo htmlspecialchars($s['endpoint']); ?>"
							placeholder="https://api.sedasanj.ir/v1/ingest/calls">
						<span class="help-block"><?php echo _("Full ingest endpoint URL. Must use HTTPS."); ?></span>
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="api_key"><?php echo _("API Key"); ?></label>
					<div class="col-sm-6">
						<input type="password" class="form-control" id="api_key" name="api_key"
							value="" placeholder="<?php echo $s['api_key'] !== '' ? htmlspecialchars(_('Configured - leave blank to keep'), ENT_QUOTES, 'UTF-8') : ''; ?>"
							autocomplete="new-password">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="auth_header">
						<?php echo _("Authentication"); ?>
						<?php echo $helpIcon(
							_('Authentication'),
							_("Header name and scheme used to send the API key. The ingest endpoint accepts either 'Authorization: Bearer &lt;api-key&gt;' (the default) or 'X-API-Key: &lt;api-key&gt;'. Leave the scheme blank when using the X-API-Key header form.")
						); ?>
					</label>
					<div class="col-sm-3">
						<input type="text" class="form-control" id="auth_header" name="auth_header"
							value="<?php echo htmlspecialchars($s['auth_header']); ?>"
							placeholder="<?php echo htmlspecialchars(_('Header name'), ENT_QUOTES, 'UTF-8'); ?>">
					</div>
					<div class="col-sm-3">
						<input type="text" class="form-control" id="auth_scheme" name="auth_scheme"
							value="<?php echo htmlspecialchars($s['auth_scheme']); ?>"
							placeholder="<?php echo htmlspecialchars(_('Scheme (e.g. Bearer)'), ENT_QUOTES, 'UTF-8'); ?>">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="archive_password">
						<?php echo _("ZIP Archive Password"); ?>
						<?php echo $helpIcon(
							_('ZIP Archive Password'),
							_("Only needed for password-protected AES-256 ZIP uploads. Sent as the X-CBI-Archive-Password header; the password is never placed in a URL or query string. Leave blank for normal (WAV / GZIP / unencrypted ZIP) uploads. Requires the vendored 7zzs binary for this box's architecture (x86_64/aarch64) - if it's missing, saving with a password set will fail at upload time with a clear error rather than silently.")
						); ?>
					</label>
					<div class="col-sm-6">
						<input type="password" class="form-control" id="archive_password" name="archive_password"
							value="" placeholder="<?php echo $s['archive_password'] !== '' ? htmlspecialchars(_('Configured - leave blank to keep'), ENT_QUOTES, 'UTF-8') : ''; ?>"
							autocomplete="new-password">
						<?php if ($s['archive_password'] !== ''): ?><label class="checkbox-inline"><input type="checkbox" name="clear_archive_password" value="1"> <?php echo _("Remove the current ZIP password"); ?></label><?php endif; ?>
						<span class="help-block"><?php echo _("Sent as the X-CBI-Archive-Password header; only used with AES-256 ZIP archives."); ?></span>
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="verify_tls"><?php echo _("Verify TLS Certificate"); ?></label>
					<div class="col-sm-6">
						<label class="switch">
							<input type="checkbox" id="verify_tls" name="verify_tls" value="1" <?php echo ($s['verify_tls'] === '1' ? 'checked' : ''); ?>>
							<span class="slider round"></span>
						</label>
						<span class="help-block"><?php echo _("Leave enabled unless you have a specific reason (e.g. a self-signed cert on an internal endpoint)."); ?></span>
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="timeout_seconds"><?php echo _("Timeout (seconds)"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="timeout_seconds" name="timeout_seconds"
							value="<?php echo htmlspecialchars($s['timeout_seconds']); ?>" min="1">
					</div>
					<label class="col-sm-2 control-label" for="immediate_retries"><?php echo _("Immediate Retries"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="immediate_retries" name="immediate_retries"
							value="<?php echo htmlspecialchars($s['immediate_retries']); ?>" min="0">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="upload_format">
						<?php echo _("Upload Transport"); ?>
						<?php echo $helpIcon(
							_('Upload Transport'),
							_("Must match the API key: GZIP, unencrypted ZIP, or AES-256 ZIP when an archive password is configured. This does not change the local mono archive format.")
						); ?>
					</label>
					<div class="col-sm-6">
						<select class="form-control" id="upload_format" name="upload_format">
							<option value="gzip" <?php echo ($s['upload_format'] === 'gzip' ? 'selected' : ''); ?>>GZIP</option>
							<option value="zip" <?php echo ($s['upload_format'] === 'zip' ? 'selected' : ''); ?>>ZIP</option>
							<option value="wav" <?php echo ($s['upload_format'] === 'wav' ? 'selected' : ''); ?>>WAV (legacy)</option>
						</select>
					</div>
				</div>

			</div><!-- /tab-endpoint -->

			<!-- ================= Recording Watcher ================= -->
			<div role="tabpanel" class="tab-pane" id="tab-watcher">

				<div class="form-group">
					<label class="col-sm-3 control-label" for="watch_dir"><?php echo _("Watch Directory"); ?></label>
					<div class="col-sm-6">
						<input type="text" class="form-control" id="watch_dir" name="watch_dir"
							value="<?php echo htmlspecialchars($s['watch_dir']); ?>">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="filename_pattern"><?php echo _("Filename Pattern (regex)"); ?></label>
					<div class="col-sm-8">
						<input type="text" class="form-control" id="filename_pattern" name="filename_pattern"
							value="<?php echo htmlspecialchars($s['filename_pattern']); ?>">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="exclude_patterns">
						<?php echo _("Exclude Pattern (regex)"); ?>
						<?php echo $helpIcon(
							_('Exclude Pattern'),
							_("Files matching this are ignored by the sweeper. Only needs to exclude the raw per-leg recv_*/trans_* files. The sweeper only ever recovers stereo_*.wav recordings that are still in the recording tree - it never uploads the local archive file.")
						); ?>
					</label>
					<div class="col-sm-8">
						<input type="text" class="form-control" id="exclude_patterns" name="exclude_patterns"
							value="<?php echo htmlspecialchars($s['exclude_patterns']); ?>">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="min_file_age_seconds"><?php echo _("Minimum File Age (seconds)"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="min_file_age_seconds" name="min_file_age_seconds"
							value="<?php echo htmlspecialchars($s['min_file_age_seconds']); ?>" min="0">
					</div>
				</div>

			</div><!-- /tab-watcher -->

			<div role="tabpanel" class="tab-pane" id="tab-missed-calls">
				<div class="alert alert-info"><?php echo _("Missed calls are read from the Asterisk CDR table and uploaded without audio. Enable unanswered=yes in cdr.conf and reload CDR before turning this on."); ?></div>
				<div class="alert <?php echo ($missedCallSummary['cdr_available'] && $missedCallSummary['unanswered_ready']) ? 'alert-success' : 'alert-warning'; ?>">
					<?php echo $missedCallSummary['cdr_available'] ? _("CDR table is available.") : _("CDR table is unavailable."); ?>
					<?php echo $missedCallSummary['unanswered_ready'] ? _("Unanswered CDR recording is enabled.") : _("unanswered=yes is not enabled in cdr.conf."); ?>
				</div>
				<div class="row sj-stats">
					<div class="col-sm-4"><div class="sj-stat"><span><?php echo _("Queued"); ?></span><strong><?php echo (int) $missedCallSummary['queued']; ?></strong></div></div>
					<div class="col-sm-4"><div class="sj-stat"><span><?php echo _("Delivered markers"); ?></span><strong><?php echo (int) $missedCallSummary['delivered']; ?></strong></div></div>
					<div class="col-sm-4"><div class="sj-stat"><span><?php echo _("Failed"); ?></span><strong><?php echo (int) $missedCallSummary['failed']; ?></strong></div></div>
				</div>
				<div class="form-group"><label class="col-sm-3 control-label" for="missed_calls_enabled"><?php echo _("Enable Missed Calls"); ?></label><div class="col-sm-6"><label class="switch"><input type="checkbox" id="missed_calls_enabled" name="missed_calls_enabled" value="1" <?php echo ($s['missed_calls_enabled'] === '1' ? 'checked' : ''); ?>><span class="slider round"></span></label></div></div>
				<div class="form-group"><label class="col-sm-3 control-label" for="missed_calls_poll_interval_seconds"><?php echo _("Poll Interval (seconds)"); ?></label><div class="col-sm-3"><input type="number" class="form-control" id="missed_calls_poll_interval_seconds" name="missed_calls_poll_interval_seconds" min="10" max="3600" value="<?php echo htmlspecialchars($s['missed_calls_poll_interval_seconds']); ?>"></div></div>
			</div>

			<div role="tabpanel" class="tab-pane" id="tab-voicemail">
				<div class="alert alert-info"><?php echo _("Voicemail messages are copied and uploaded without changing, moving, or deleting anything in the mailbox. Each message is transcribed and analyzed without consuming call-processing credit. The first scan ignores existing messages unless backfill is enabled."); ?></div>
				<div class="row sj-stats">
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Uploaded"); ?></span><strong><?php echo (int) $voicemailSummary['uploaded']; ?></strong></div></div>
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Ignored existing messages"); ?></span><strong><?php echo (int) $voicemailSummary['ignored']; ?></strong></div></div>
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Awaiting retry"); ?></span><strong><?php echo (int) $voicemailSummary['spooled']; ?></strong></div></div>
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Failed"); ?></span><strong><?php echo (int) $voicemailSummary['failed']; ?></strong></div></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_enabled"><?php echo _("Enable Voicemail Upload"); ?></label>
					<div class="col-sm-6"><label class="switch"><input type="checkbox" id="voicemail_enabled" name="voicemail_enabled" value="1" <?php echo ($s['voicemail_enabled'] === '1' ? 'checked' : ''); ?>><span class="slider round"></span></label></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_spool_dir"><?php echo _("Voicemail Spool Directory"); ?></label>
					<div class="col-sm-6"><input class="form-control" id="voicemail_spool_dir" name="voicemail_spool_dir" value="<?php echo htmlspecialchars($s['voicemail_spool_dir']); ?>"></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_folders"><?php echo _("Folders"); ?></label>
					<div class="col-sm-6"><input class="form-control" id="voicemail_folders" name="voicemail_folders" value="<?php echo htmlspecialchars($s['voicemail_folders']); ?>"><span class="help-block"><?php echo _("Comma-separated folder names. The temporary folder is always excluded."); ?></span></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_mailbox_filter"><?php echo _("Mailbox Filter"); ?></label>
					<div class="col-sm-6"><input class="form-control" id="voicemail_mailbox_filter" name="voicemail_mailbox_filter" value="<?php echo htmlspecialchars($s['voicemail_mailbox_filter']); ?>" placeholder="1001,1002"><span class="help-block"><?php echo _("Leave blank to scan every mailbox."); ?></span></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_backfill"><?php echo _("Upload Existing Messages"); ?></label>
					<div class="col-sm-6"><label class="switch"><input type="checkbox" id="voicemail_backfill" name="voicemail_backfill" value="1" <?php echo ($s['voicemail_backfill'] === '1' ? 'checked' : ''); ?>><span class="slider round"></span></label><span class="help-block"><?php echo _("Disabled by default. When enabled, all complete messages in selected folders are uploaded."); ?></span></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_sweep_interval_seconds"><?php echo _("Scan Interval (seconds)"); ?></label>
					<div class="col-sm-3"><input type="number" class="form-control" id="voicemail_sweep_interval_seconds" name="voicemail_sweep_interval_seconds" min="10" max="86400" value="<?php echo htmlspecialchars($s['voicemail_sweep_interval_seconds']); ?>"></div>
				</div>
				<div class="form-group">
					<label class="col-sm-3 control-label" for="voicemail_audio_preference"><?php echo _("Audio Format Preference"); ?></label>
					<div class="col-sm-6"><input class="form-control" id="voicemail_audio_preference" name="voicemail_audio_preference" value="<?php echo htmlspecialchars($s['voicemail_audio_preference']); ?>"><span class="help-block"><?php echo _("Comma-separated source formats in priority order."); ?></span></div>
				</div>
			</div>

			<!-- ================= Post-Upload & Archive ================= -->
			<div role="tabpanel" class="tab-pane" id="tab-post">

				<div class="form-group">
					<label class="col-sm-3 control-label" for="on_success"><?php echo _("After a Successful Upload"); ?></label>
					<div class="col-sm-3">
						<select class="form-control" id="on_success" name="on_success">
							<?php foreach (array(
								'keep'   => _('Keep in place'),
								'delete' => _('Delete local file'),
								'move'   => _('Move to another directory'),
							) as $val => $label): ?>
								<option value="<?php echo $val; ?>" <?php echo ($s['on_success'] === $val ? 'selected' : ''); ?>><?php echo $label; ?></option>
							<?php endforeach; ?>
						</select>
					</div>
					<label class="col-sm-2 control-label" for="move_dir"><?php echo _("Move-to Directory"); ?></label>
					<div class="col-sm-3">
						<input type="text" class="form-control" id="move_dir" name="move_dir"
							value="<?php echo htmlspecialchars($s['move_dir']); ?>">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="archive_format">
						<?php echo _("Archive Format"); ?>
						<?php echo $helpIcon(
							_('Archive Format'),
							_("Format for the local mono copy kept alongside the original recording, encoded with the system ffmpeg binary. 'gsm' is the default; any format ffmpeg supports (mp3, ogg, opus, wav, ...) can be used instead - just set this to the desired file extension. Does not affect what's uploaded - that's always the original stereo recording.")
						); ?>
					</label>
					<div class="col-sm-3">
						<input type="text" class="form-control" id="archive_format" name="archive_format"
							value="<?php echo htmlspecialchars($s['archive_format']); ?>">
						<span class="help-block"><?php echo _("Mono copy kept alongside the original recording."); ?></span>
					</div>
				</div>

			</div><!-- /tab-post -->

			<!-- ================= Retry Queue & Sweeper ================= -->
			<div role="tabpanel" class="tab-pane" id="tab-retry">
				<div class="row sj-stats">
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Pending"); ?></span><strong><?php echo (int) $queueSummary['pending']; ?></strong></div></div>
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Blocked by credit"); ?></span><strong><?php echo (int) $queueSummary['blocked_credit']; ?></strong></div></div>
					<div class="col-sm-3"><div class="sj-stat"><span><?php echo _("Failed"); ?></span><strong><?php echo (int) $queueSummary['failed']; ?></strong></div></div>
				</div>
				<?php if ($queueSummary['last_error'] !== ''): ?><div class="alert alert-warning"><strong><?php echo _("Last error"); ?>:</strong> <?php echo htmlspecialchars($queueSummary['last_error'], ENT_QUOTES, 'UTF-8'); ?></div><?php endif; ?>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="max_retries"><?php echo _("Max Retries"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="max_retries" name="max_retries"
							value="<?php echo htmlspecialchars($s['max_retries']); ?>" min="0">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="credit_retry_seconds"><?php echo _("Credit Retry (s)"); ?></label>
					<div class="col-sm-3"><input type="number" class="form-control" id="credit_retry_seconds" name="credit_retry_seconds" value="<?php echo htmlspecialchars($s['credit_retry_seconds']); ?>" min="60"></div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="retry_base_seconds">
						<?php echo _("Retry Base (s)"); ?>
						<?php echo $helpIcon(_('Retry Base'), _('Initial delay before the first retry attempt.')); ?>
					</label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="retry_base_seconds" name="retry_base_seconds"
							value="<?php echo htmlspecialchars($s['retry_base_seconds']); ?>" min="0">
					</div>
					<label class="col-sm-2 control-label" for="retry_max_seconds">
						<?php echo _("Retry Cap (s)"); ?>
						<?php echo $helpIcon(_('Retry Cap'), _('Maximum delay between retry attempts, after backoff.')); ?>
					</label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="retry_max_seconds" name="retry_max_seconds"
							value="<?php echo htmlspecialchars($s['retry_max_seconds']); ?>" min="0">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="sweep_interval_seconds"><?php echo _("Sweep Interval (s)"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="sweep_interval_seconds" name="sweep_interval_seconds"
							value="<?php echo htmlspecialchars($s['sweep_interval_seconds']); ?>" min="0">
					</div>
					<label class="col-sm-2 control-label" for="stale_processing_seconds">
						<?php echo _("Stale After (s)"); ?>
						<?php echo $helpIcon(
							_('Stale After'),
							_("How long an item can sit in 'processing' before the sweeper considers it stale and requeues it.")
						); ?>
					</label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="stale_processing_seconds" name="stale_processing_seconds"
							value="<?php echo htmlspecialchars($s['stale_processing_seconds']); ?>" min="0">
					</div>
				</div>

				<div class="form-group">
					<label class="col-sm-3 control-label" for="retention_days"><?php echo _("Retention (days)"); ?></label>
					<div class="col-sm-3">
						<input type="number" class="form-control" id="retention_days" name="retention_days"
							value="<?php echo htmlspecialchars($s['retention_days']); ?>" min="0">
					</div>
				</div>

			</div><!-- /tab-retry -->

			<!-- ================= Logging ================= -->
			<div role="tabpanel" class="tab-pane" id="tab-logging">

				<!-- Part of the main settings form (POST) -->
				<div class="form-group">
					<label class="col-sm-3 control-label" for="log_level"><?php echo _("Log Level"); ?></label>
					<div class="col-sm-3">
						<select class="form-control" id="log_level" name="log_level">
							<?php foreach (array('DEBUG', 'INFO', 'WARNING', 'ERROR') as $lvl): ?>
								<option value="<?php echo $lvl; ?>" <?php echo ($s['log_level'] === $lvl ? 'selected' : ''); ?>><?php echo $lvl; ?></option>
							<?php endforeach; ?>
						</select>
						<span class="help-block"><?php echo _("Verbosity written to the service's log file."); ?></span>
					</div>
				</div>

				<!-- Log viewer: separate GET form. Inputs use form="log-viewer-form"
				     so they submit to the standalone <form> rendered after the
				     main settings form (nested <form> elements are invalid HTML). -->
				<hr>

				<h4 style="margin-top: 0;">
					<i class="fa fa-list-alt"></i> <?php echo _("Recent Log Entries"); ?>
				</h4>

				<div class="sj-log-controls">
					<input form="log-viewer-form" type="hidden" name="display" value="recuploader">

					<div class="sj-log-field">
						<label for="log_min_level"><?php echo _("Minimum level"); ?></label>
						<select form="log-viewer-form" class="form-control" id="log_min_level" name="log_min_level">
							<?php foreach ($logLevels as $lvl): ?>
								<option value="<?php echo $lvl; ?>" <?php echo ($logMinLevel === $lvl ? 'selected' : ''); ?>><?php echo $lvl; ?></option>
							<?php endforeach; ?>
						</select>
					</div>

					<div class="sj-log-field">
						<label for="log_max_lines"><?php echo _("Lines"); ?></label>
						<input form="log-viewer-form" type="number" class="form-control" id="log_max_lines" name="log_max_lines"
							value="<?php echo (int) $logMaxLines; ?>" min="10" max="2000">
					</div>

					<button id="log-refresh-btn" form="log-viewer-form" type="submit" class="btn btn-default">
						<i class="fa fa-refresh"></i> <?php echo _("Refresh Logs"); ?>
					</button>
				</div>

				<!-- Replaced in place by AJAX on "Refresh Logs" (see script block below) -
				     this id is the only thing that gets rewritten, so refreshing never
				     touches the rest of the page or the active tab. Server-rendered here
				     for the initial page load only. -->
				<div id="log-viewer-results">
				<?php if (empty($logLines)): ?>
					<p class="text-muted">
						<?php echo _("No log lines found at this level yet (or the log file isn't readable)."); ?>
						<code>/var/log/asterisk-recording-uploader/uploader.log</code>
					</p>
				<?php else: ?>
					<pre class="sj-log"><?php
						foreach (array_reverse($logLines) as $line) {
							echo htmlspecialchars($line) . "\n";
						}
					?></pre>
					<p class="text-muted">
						<?php printf(
							_('Showing the most recent %1$d line(s) at %2$s level and above, newest first.'),
							count($logLines),
							htmlspecialchars($logMinLevel, ENT_QUOTES, 'UTF-8')
						); ?>
					</p>
				<?php endif; ?>
				</div><!-- /log-viewer-results -->

			</div><!-- /tab-logging -->

		</div><!-- /tab-content -->

		<div class="form-group sj-actions">
			<div class="col-sm-offset-3 col-sm-9">
				<button type="submit" name="recuploader_save" value="1" class="btn btn-sj">
					<i class="fa fa-save"></i> <?php echo _("Save &amp; Restart Service"); ?>
				</button>
			</div>
		</div>
		</div><!-- /sj-card -->

	</form>

	<!-- Standalone GET form referenced by the log-viewer controls via the
	     HTML5 form="log-viewer-form" attribute (see #tab-logging). -->
	<form id="log-viewer-form" method="get" action="config.php"></form>

	<!-- ================= Service Information ================= -->
	<div class="panel panel-default sj-card sj-info">
		<div class="panel-heading">
			<h3 class="panel-title"><i class="fa fa-info-circle"></i> <?php echo _("Service Information"); ?></h3>
		</div>
		<div class="panel-body">
			<dl class="dl-horizontal" style="margin-bottom: 0;">
				<dt><?php echo _("Service"); ?></dt>
				<dd><code>asterisk-recording-uploader.service</code></dd>

				<dt><?php echo _("Config file"); ?></dt>
				<dd><code>/etc/asterisk-recording-uploader/config.ini</code></dd>

				<dt><?php echo _("Log file"); ?></dt>
				<dd><code>/var/log/asterisk-recording-uploader/uploader.log</code></dd>

				<dt><?php echo _("Journal"); ?></dt>
				<dd><code>journalctl -u asterisk-recording-uploader.service</code></dd>
			</dl>
		</div>
	</div>

	<footer class="sj-footer">
		<?php if ($logoSvg !== false): ?><span class="sj-logo"><?php echo $logoSvg; ?></span>&middot;<?php endif; ?>
		<a href="https://sedasanj.ir" target="_blank" rel="noopener">sedasanj.ir</a>
	</footer>

</div>

<script>
	$(function () {

		/* ---- Initialize help popovers -----------------------------------
		 * FreePBX's admin chrome does not auto-init popovers for custom
		 * modules, so we do it explicitly here. container: 'body' keeps the
		 * popover from being clipped by the tab pane; html: true lets us
		 * render the (already-escaped) data-content / data-original-title
		 * values correctly. */
		$('[data-toggle="popover"]').each(function () {
			var $el = $(this);
			$el.popover({
				trigger:   'hover',
				placement: $el.data('placement') || 'top',
				container: 'body',
				html:      true,
				title:     $el.attr('data-original-title') || '',
				content:   $el.attr('data-content') || ''
			});
		});

		/* ---- Gzip confirmation -----------------------------------------
		 * Toggling gzip (either direction) changes what the endpoint
		 * receives, so ask first. Cancel reverts the checkbox; OK leaves it
		 * toggled (the page's Save button is still needed to persist it). */
		$('select[name="upload_format"]').on('change', function () {
			var $select = $(this);
			var previous = $select.data('previous') || 'gzip';
			var msg = <?php echo json_encode(_("Turning gzip on/off changes what your endpoint receives. Make sure your endpoint is updated to match before saving. Continue?")); ?>;
			if (!confirm(msg)) {
				$select.val(previous);
			} else {
				$select.data('previous', $select.val());
			}
		}).data('previous', $('select[name="upload_format"]').val());

		/* ---- Log viewer refresh (AJAX, no page reload) -------------------
		 * This used to be a plain GET <form> submit to config.php, which
		 * reloaded the whole admin page - and since Bootstrap tabs reset to
		 * whichever pane has class="active" in the markup (Upload Endpoint)
		 * on every fresh page load, that made "Refresh Logs" look like it
		 * was kicking the admin back to a different section. Routing this
		 * through BMO's ajax.php instead (Recuploader::ajaxHandler(),
		 * command=getlogs) means only the #log-viewer-results markup below
		 * is replaced - no navigation, no tab change, nothing else on the
		 * page is touched. */
		var aruLogNoneMsg = <?php echo json_encode(
			_("No log lines found at this level yet (or the log file isn't readable).")
		); ?>;
		var aruLogErrorMsg = <?php echo json_encode(_('Could not refresh logs - see the browser console for details.')); ?>;
		var aruLogSummaryFmt = <?php echo json_encode(
			_('Showing the most recent %1$d line(s) at %2$s level and above, newest first.')
		); ?>;

		function aruEscapeHtml(str) {
			return $('<div>').text(String(str)).html();
		}

		function aruRenderLogResults(data) {
			var $results = $('#log-viewer-results');
			if (!data || data.status !== true) {
				$results.html('<p class="text-danger">' + aruEscapeHtml(aruLogErrorMsg) + '</p>');
				return;
			}
			var lines = data.lines || [];
			if (!lines.length) {
				$results.html(
					'<p class="text-muted">' + aruEscapeHtml(aruLogNoneMsg) +
					' <code>/var/log/asterisk-recording-uploader/uploader.log</code></p>'
				);
				return;
			}
			var html = '<pre class="sj-log">';
			$.each(lines, function (i, line) {
				html += aruEscapeHtml(line) + '\n';
			});
			html += '</pre>';
			var summary = aruLogSummaryFmt
				.replace('%1$d', data.count)
				.replace('%2$s', aruEscapeHtml(data.min_level));
			html += '<p class="text-muted">' + summary + '</p>';
			$results.html(html);
		}

		$('#log-refresh-btn').on('click', function (e) {
			e.preventDefault(); // do NOT let this fall through to the GET form submit
			var $btn = $(this);
			var ajaxUrl = (window.FreePBX && FreePBX.ajaxurl) ? FreePBX.ajaxurl : 'ajax.php';
			$btn.prop('disabled', true);
			$.ajax({
				url: ajaxUrl,
				method: 'GET',
				dataType: 'json',
				data: {
					module: 'recuploader',
					command: 'getlogs',
					log_min_level: $('#log_min_level').val(),
					log_max_lines: $('#log_max_lines').val()
				}
			}).done(function (data) {
				aruRenderLogResults(data);
			}).fail(function () {
				aruRenderLogResults(null);
			}).always(function () {
				$btn.prop('disabled', false);
			});
		});

	});
</script>
