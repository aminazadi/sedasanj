// Read CSV records incrementally, including quoted newlines and escaped quotes.
export async function* csvRecords(file) {
  const prefix = new Uint8Array(await file.slice(0, 3).arrayBuffer());
  let encoding = prefix[0] === 255 && prefix[1] === 254 ? 'utf-16le' : prefix[0] === 254 && prefix[1] === 255 ? 'utf-16be' : 'utf-8';
  if (encoding === 'utf-8') {
    const probe = new TextDecoder('utf-8', { fatal: true });
    try {
      for (let offset = 0; offset < file.size; offset += 65536) {
        probe.decode(await file.slice(offset, offset + 65536).arrayBuffer(), { stream: true });
      }
      probe.decode();
    } catch { encoding = 'windows-1256'; }
  }
  const decoder = new TextDecoder(encoding);
  let record = '', quoted = false, line = 1;
  for (let offset = 0; offset < file.size; offset += 65536) {
    const end = Math.min(file.size, offset + 65536);
    const text = decoder.decode(await file.slice(offset, end).arrayBuffer(), { stream: end < file.size });
    for (const character of text) {
      record += character;
      if (character === '"') quoted = !quoted;
      if ((character === '\n' || character === '\r') && !quoted) {
        if (record.trim()) yield { text: record, line: line++, progress: end / file.size };
        record = '';
      }
    }
  }
  if (record.trim()) yield { text: record + '\n', line, progress: 1 };
}

export function csvCells(record, delimiter) {
  const cells = []; let cell = '', quoted = false;
  for (let i = 0; i < record.length; i++) {
    const c = record[i];
    if (c === '"') {
      if (quoted && record[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (c === delimiter && !quoted) { cells.push(cell); cell = ''; }
    else cell += c;
  }
  cells.push(cell.trimEnd());
  return cells;
}

export function phoneKey(raw) {
  let value = raw.trim().replace(/[۰-۹]/g, c => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c))).replace(/[٠-٩]/g, c => String('٠١٢٣٤٥٦٧٨٩'.indexOf(c)));
  value = value.replace(/^(\d+)[.,]0+$/, '$1');
  if (/[^\d \-()+./\u200c\u200e\u200f\u00a0\u202a\u202c]/.test(value)) return null;
  let digits = value.replace(/\D/g, '');
  if (digits.startsWith('0098')) digits = digits.slice(4);
  else if (digits.startsWith('98') && digits.length >= 12) digits = digits.slice(2);
  if (digits.length === 10 && !digits.startsWith('0')) digits = '0' + digits;
  return digits.length >= 3 && digits.length <= 15 ? digits : null;
}

export async function importContacts(file, mode, dryRun, send, onProgress) {
  const report = { dry_run: dryRun, mode, total_rows: 0, created: 0, updated: 0, skipped: 0, error_count: 0, errors: [], accepted_numbers: [] };
  const seen = new Set();
  let header = '', delimiter = ',', phoneColumn = -1, batch = [], bytes = 0;
  const addError = (row, message) => { report.error_count++; if (report.errors.length < 100) report.errors.push({ row, message }); };
  async function flush(progress) {
    if (!batch.length) return;
    const body = new FormData();
    body.append('file', new Blob([header, ...batch.map(r => r.text)], { type: 'text/csv;charset=utf-8' }), 'contacts.csv');
    body.append('mode', mode); body.append('dry_run', String(dryRun));
    const result = await send(body);
    for (const key of result.accepted_numbers) seen.add(key);
    for (const key of ['created', 'updated', 'skipped']) report[key] += result[key];
    report.total_rows += result.total_rows;
    report.error_count += result.error_count;
    for (const error of result.errors) {
      if (report.errors.length < 100) report.errors.push({ ...error, row: batch[error.row - 2]?.line ?? error.row });
    }
    batch = []; bytes = 0;
    onProgress(Math.min(99, Math.floor(progress * 100)), dryRun ? 'در حال بررسی فایل' : 'در حال ثبت مخاطبان');
  }
  onProgress(0, 'در حال خواندن فایل');
  for await (const record of csvRecords(file)) {
    if (!header) {
      header = record.text;
      delimiter = [',', ';', '\t'].sort((a, b) => header.split(b).length - header.split(a).length)[0];
      const aliases = ['phone', 'phonenumber', 'number', 'mobile', 'mobilenumber', 'tel', 'telephone', 'cell', 'شماره', 'شمارهتلفن', 'شمارهموبایل', 'شمارهتماس', 'تلفن', 'موبایل', 'همراه', 'تلفنهمراه'];
      phoneColumn = csvCells(header, delimiter).findIndex(c => aliases.includes(c.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '').replace(/ي/g, 'ی').replace(/ك/g, 'ک')));
      continue;
    }
    const key = phoneKey(csvCells(record.text, delimiter)[phoneColumn] ?? '');
    if (key && seen.has(key)) {
      report.total_rows++;
      addError(record.line, 'این شماره در ردیف بالاتر همین فایل هم آمده و نادیده گرفته شد');
      continue;
    }
    batch.push(record); bytes += record.text.length;
    if (batch.length >= 250 || bytes >= 262144) await flush(record.progress);
  }
  await flush(1);
  if (!report.total_rows) throw new Error('فایل خالی است؛ فایل CSV دارای عنوان و مخاطبان انتخاب کنید.');
  onProgress(100, dryRun ? 'بررسی کامل شد' : 'ثبت کامل شد');
  return report;
}
