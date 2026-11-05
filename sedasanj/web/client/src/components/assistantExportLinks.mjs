export function exportDownloadPath(file) {
  return `/v1/assistant/exports/${encodeURIComponent(file.export_id)}/download`;
}

export function exportFiles(runs) {
  return [...new Map(runs.flatMap((run) => run.files || []).map((file) => [file.export_id, file])).values()];
}

// Add missing downloads to the message AST so filenames remain literal text.
export function appendExportLinks(tree, files) {
  const linked = new Set();
  const definitions = new Map();
  function visit(node, callback) {
    callback(node);
    for (const child of node.children || []) visit(child, callback);
  }
  visit(tree, (node) => {
    if (node.type === "definition") definitions.set(node.identifier, node.url);
  });
  visit(tree, (node) => {
    if (node.type === "link") linked.add(node.url);
    if (node.type === "linkReference") linked.add(definitions.get(node.identifier));
  });
  const unique = [...new Map(files.map((file) => [file.export_id, file])).values()];
  for (const file of unique) {
    const url = exportDownloadPath(file);
    if (linked.has(url)) continue;
    tree.children.push({
      type: "paragraph",
      children: [{ type: "link", url, children: [{ type: "text", value: `دریافت ${file.name}` }] }],
    });
  }
}
