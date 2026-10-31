(function () {
  'use strict';
  var root = document.getElementById('sj-issabel');
  var content = document.getElementById('sj-content');
  var message = document.getElementById('sj-message');
  var csrf = root.dataset.csrf;
  var tabs = {settings: 'تنظیمات', models: 'مدل‌ها و اتصال', health: 'سلامت', queue: 'صف ارسال', extensions: 'داخلی‌ها', logs: 'لاگ', updates: 'به‌روزرسانی', support: 'پشتیبانی'};
  var labels = {general:'اتصال', upload:'ارسال', post_upload:'پس از ارسال', archive:'آرشیو', watcher:'بازیابی ضبط', missed_calls:'تماس ازدست‌رفته', voicemail:'پیام صوتی', queue:'صف', state:'نگهداری', logging:'لاگ'};
  var fields = {endpoint:'نشانی ارسال',api_key:'کلید API؛ خالی برای حفظ مقدار قبلی',archive_password:'رمز آرشیو؛ خالی برای حفظ مقدار قبلی',timeout_seconds:'مهلت اتصال (ثانیه)',immediate_retries:'تلاش فوری',format:'قالب فایل',on_success:'عملیات پس از ارسال',move_dir:'پوشه آرشیو',filename_pattern:'الگوی نام فایل',min_file_age_seconds:'حداقل عمر فایل (ثانیه)',enabled:'فعال',poll_interval_seconds:'فاصله بررسی (ثانیه)',spool_dir:'پوشه فایل‌ها',folders:'پوشه‌های پیام صوتی',mailbox_filter:'فیلتر صندوق',backfill:'بازیابی پیام‌های قبلی',sweep_interval_seconds:'فاصله بازیابی (ثانیه)',audio_preference:'اولویت قالب صوتی',max_retries:'حداکثر تلاش',retry_base_seconds:'فاصله اولیه تلاش',retry_max_seconds:'حداکثر فاصله تلاش',credit_retry_seconds:'فاصله تلاش پس از اتمام اعتبار',retention_days:'نگهداری آرشیو (روز)',stale_processing_seconds:'مهلت پردازش معطل',log_level:'سطح لاگ',mask_numbers:'پوشاندن شماره‌ها'};
  var allowed = {general:['endpoint','api_key','archive_password','timeout_seconds','immediate_retries'],upload:['format'],post_upload:['on_success','move_dir'],archive:['format'],watcher:['filename_pattern','min_file_age_seconds'],missed_calls:['enabled','poll_interval_seconds'],voicemail:['enabled','spool_dir','folders','mailbox_filter','backfill','sweep_interval_seconds','audio_preference'],queue:['max_retries','retry_base_seconds','retry_max_seconds','credit_retry_seconds'],state:['sweep_interval_seconds','stale_processing_seconds','retention_days'],logging:['log_level','mask_numbers']};
  function node(tag, text) { var el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; }
  function button(label, action) { var b = node('button', label); b.type='button'; b.onclick=action; return b; }
  function call(op, extra) {
    message.textContent = 'در حال بررسی…';
    var request = Object.assign({op:op}, extra || {});
    return fetch('/admin/modules/recuploader/ajax.php', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'csrf='+encodeURIComponent(csrf)+'&payload='+encodeURIComponent(JSON.stringify(request))})
      .then(function (r) { if (!r.ok) throw new Error('دسترسی یا نشست کاربری را بررسی کنید.'); return r.json(); })
      .then(function (r) { if (!r.ok) throw new Error((r.code || '')+' — '+(r.message || 'راهنمای خطا و سلامت را بررسی کنید.')); message.textContent=''; return r.data; })
      .catch(function (e) { message.textContent=e.message; throw e; });
  }
  function show(data) { var pre=node('pre',JSON.stringify(data,null,2)); pre.dir='ltr'; content.appendChild(pre); }
  function run(op, extra) { return call(op,extra).then(function(data){content.textContent='';show(data);}); }
  function settings() {
    call('settings').then(function (cfg) {
      content.textContent=''; var form=node('form');
      Object.keys(allowed).forEach(function(section){
        var box=node('fieldset'); box.appendChild(node('legend',labels[section]));
        allowed[section].forEach(function(key){
          var label=node('label',fields[key] || key); var input=node('input'); var value=cfg[section][key];
          input.type=typeof value==='boolean'?'checkbox':typeof value==='number'?'number':(key==='api_key'||key==='archive_password')?'password':'text';
          input.dir='ltr'; input.name=section+'.'+key; input.dataset.kind=typeof value;
          if(typeof value==='boolean')input.checked=value;else input.value=value;
          input.autocomplete='off';label.appendChild(input);box.appendChild(label);
        });form.appendChild(box);
      });
      form.appendChild(button('ذخیره و راه‌اندازی مجدد',function(){
        var result={};form.querySelectorAll('input').forEach(function(input){var names=input.name.split('.');if(!result[names[0]])result[names[0]]={};result[names[0]][names[1]]=input.dataset.kind==='boolean'?input.checked:input.dataset.kind==='number'?Number(input.value):input.value;});
        call('save',{settings:result}).then(function(){message.textContent='تنظیمات ذخیره شد.';});
      }));content.appendChild(form);
      var profile=node('textarea');profile.placeholder='محتوای فایل تنظیمات ایزابل';profile.dir='ltr';content.appendChild(profile);
      content.appendChild(button('بررسی و پیش‌نمایش تنظیمات', function () {
        call('import', {profile: profile.value}).then(function (data) {
          show(data);
          content.appendChild(button('اعمال تنظیمات تأییدشده', function () {
            call('applyimport').then(settings);
          }));
        });
      }));
      var runtime=node('input');runtime.dir='ltr';runtime.placeholder='/opt/remi/php74/root/usr/bin/php';content.appendChild(node('p','تغییر PHP موتور پس از اعتبارسنجی در فعال‌سازی مدیر سیستم اعمال می‌شود.'));content.appendChild(runtime);
      content.appendChild(button('نمایش فرمان فعال‌سازی',function(){if(!/^\/[A-Za-z0-9_./-]+$/.test(runtime.value)||runtime.value.indexOf('..')!==-1)return;var pre=node('pre','bash /var/www/html/admin/modules/recuploader/activate.sh '+runtime.value);pre.dir='ltr';content.appendChild(pre);}));
    });
  }
  function load(){
    var url=new URL(window.location.href);var tab=url.searchParams.get('sj_tab')||'settings';if(!tabs[tab])tab='settings';
    content.textContent='';
    document.querySelectorAll('#sj-tabs a').forEach(function(a){a.className=a.dataset.tab===tab?'active':'';});
    if(tab==='settings'){settings();return;}
    if(tab==='updates'){
      content.appendChild(button('بررسی نسخه',function(){call('checkupdate').then(show);}));
      content.appendChild(button('دریافت و نصب نسخه سازگار',function(){if(window.confirm('نسخه سازگار نصب و سرویس دوباره راه‌اندازی شود؟'))call('update').then(show);}));
      content.appendChild(button('وضعیت نصب',function(){call('updatestatus').then(show);}));return;
    }
    if(tab==='logs'){
      var select=node('select');['ALL','DEBUG','INFO','WARNING','ERROR'].forEach(function(level){var option=node('option',level);option.value=level;select.appendChild(option);});select.value=url.searchParams.get('sj_level')||'ALL';
      select.onchange=function(){var next=new URL(location.href);next.searchParams.set('sj_level',select.value);history.replaceState(null,'',next);load();};content.appendChild(select);
      call('logs',{level:select.value}).then(function(data){var pre=node('pre',data.text);pre.dir='ltr';content.appendChild(pre);});return;
    }
    if(tab==='queue')content.appendChild(button('تلاش مجدد ارسال‌های ناموفق',function(){call('requeue').then(show);}));
    if(tab==='extensions')content.appendChild(button('همگام‌سازی داخلی‌ها',function(){call('sync').then(show);}));
    if(tab==='health')['start','stop','restart'].forEach(function(action){content.appendChild(button({start:'شروع سرویس',stop:'توقف سرویس',restart:'راه‌اندازی مجدد'}[action],function(){call('service',{action:action}).then(function(){load();});}));});
    if(tab==='models')content.appendChild(node('p','انتخاب مدل از تنظیمات کلید API در پنل صداسنج انجام می‌شود. نتیجه اعتبارسنجی اتصال در زیر نمایش داده می‌شود.'));
    call(tab==='models'?'models':tab).then(show);
  }
  Object.keys(tabs).forEach(function(key){var a=node('a',tabs[key]);var url=new URL(location.href);url.searchParams.set('sj_tab',key);a.href=url.toString();a.dataset.tab=key;a.onclick=function(e){e.preventDefault();history.pushState(null,'',a.href);load();};document.getElementById('sj-tabs').appendChild(a);});
  window.addEventListener('popstate',load);load();
}());
