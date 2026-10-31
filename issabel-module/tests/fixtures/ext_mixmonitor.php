<?php
// Official IssabelFoundation extensions.class.php, GPLv3+, commit 0f77edaade296e929f2159f3165ceecc7f74b267.
class extension {}
class ext_mixmonitor extends extension {
	var $file;
	var $options;
	var $postcommand;
	
	function __construct($file, $options = "", $postcommand = "") {
		$this->file = $file;
		$this->options = $options;
		$this->postcommand = $postcommand;
	}
	
	function output() {
		return "MixMonitor(".$this->file.",".$this->options.",".$this->postcommand.")";
	}
}

