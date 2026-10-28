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
<div class="container-fluid">

	<h1>
		<?php echo _("Seda Sanj"); ?>
		<small><?php echo _("Recording Uploader &middot; sedasanj.ir"); ?></small>
	</h1>

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

		<div class="tab-content" style="padding-top: 20px;">
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
				<div class="row" style="margin: 15px 0;">
					<div class="col-sm-4"><div class="well text-center"><strong><?php echo (int) $missedCallSummary['queued']; ?></strong><br><?php echo _("Queued"); ?></div></div>
					<div class="col-sm-4"><div class="well text-center"><strong><?php echo (int) $missedCallSummary['delivered']; ?></strong><br><?php echo _("Delivered markers"); ?></div></div>
					<div class="col-sm-4"><div class="well text-center"><strong><?php echo (int) $missedCallSummary['failed']; ?></strong><br><?php echo _("Failed"); ?></div></div>
				</div>
				<div class="form-group"><label class="col-sm-3 control-label" for="missed_calls_enabled"><?php echo _("Enable Missed Calls"); ?></label><div class="col-sm-6"><label class="switch"><input type="checkbox" id="missed_calls_enabled" name="missed_calls_enabled" value="1" <?php echo ($s['missed_calls_enabled'] === '1' ? 'checked' : ''); ?>><span class="slider round"></span></label></div></div>
				<div class="form-group"><label class="col-sm-3 control-label" for="missed_calls_poll_interval_seconds"><?php echo _("Poll Interval (seconds)"); ?></label><div class="col-sm-3"><input type="number" class="form-control" id="missed_calls_poll_interval_seconds" name="missed_calls_poll_interval_seconds" min="10" max="3600" value="<?php echo htmlspecialchars($s['missed_calls_poll_interval_seconds']); ?>"></div></div>
			</div>

			<div role="tabpanel" class="tab-pane" id="tab-voicemail">
				<div class="alert alert-info"><?php echo _("Voicemail messages are copied and uploaded without changing, moving, or deleting anything in the mailbox. Each message is transcribed and analyzed without consuming call-processing credit. The first scan ignores existing messages unless backfill is enabled."); ?></div>
				<div class="row" style="margin: 15px 0;">
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $voicemailSummary['uploaded']; ?></strong><br><?php echo _("Uploaded"); ?></div></div>
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $voicemailSummary['ignored']; ?></strong><br><?php echo _("Ignored existing messages"); ?></div></div>
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $voicemailSummary['spooled']; ?></strong><br><?php echo _("Awaiting retry"); ?></div></div>
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $voicemailSummary['failed']; ?></strong><br><?php echo _("Failed"); ?></div></div>
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
				<div class="row" style="margin: 15px 0;">
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $queueSummary['pending']; ?></strong><br><?php echo _("Pending"); ?></div></div>
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $queueSummary['blocked_credit']; ?></strong><br><?php echo _("Blocked by credit"); ?></div></div>
					<div class="col-sm-3"><div class="well text-center"><strong><?php echo (int) $queueSummary['failed']; ?></strong><br><?php echo _("Failed"); ?></div></div>
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

				<div class="form-inline" style="margin-bottom: 15px;">
					<input form="log-viewer-form" type="hidden" name="display" value="recuploader">

					<div class="form-group">
						<label for="log_min_level" style="margin-right: 5px;"><?php echo _("Minimum level"); ?></label>
						<select form="log-viewer-form" class="form-control" id="log_min_level" name="log_min_level" style="margin-right: 15px;">
							<?php foreach ($logLevels as $lvl): ?>
								<option value="<?php echo $lvl; ?>" <?php echo ($logMinLevel === $lvl ? 'selected' : ''); ?>><?php echo $lvl; ?></option>
							<?php endforeach; ?>
						</select>
					</div>

					<div class="form-group">
						<label for="log_max_lines" style="margin-right: 5px;"><?php echo _("Lines"); ?></label>
						<input form="log-viewer-form" type="number" class="form-control" id="log_max_lines" name="log_max_lines"
							value="<?php echo (int) $logMaxLines; ?>" min="10" max="2000"
							style="width: 100px; margin-right: 15px;">
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
					<pre style="max-height: 500px; overflow: auto; background: #1e1e1e; color: #ddd; padding: 10px; border-radius: 4px;"><?php
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

		<div class="form-group" style="margin-top: 25px;">
			<div class="col-sm-offset-3 col-sm-9">
				<button type="submit" name="recuploader_save" value="1" class="btn btn-default">
					<i class="fa fa-save"></i> <?php echo _("Save &amp; Restart Service"); ?>
				</button>
			</div>
		</div>

	</form>

	<!-- Standalone GET form referenced by the log-viewer controls via the
	     HTML5 form="log-viewer-form" attribute (see #tab-logging). -->
	<form id="log-viewer-form" method="get" action="config.php"></form>

	<!-- ================= Service Information ================= -->
	<div class="panel panel-default" style="margin-top: 30px;">
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

	<p class="text-muted" style="margin-top: 20px;">
		<?php echo _("Seda Sanj"); ?> &middot;
		<a href="https://sedasanj.ir" target="_blank" rel="noopener">sedasanj.ir</a>
	</p>

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
			var html = '<pre style="max-height: 500px; overflow: auto; background: #1e1e1e; color: #ddd; padding: 10px; border-radius: 4px;">';
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
