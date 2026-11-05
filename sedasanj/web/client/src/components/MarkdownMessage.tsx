import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";

import type { Root } from "mdast";
import type { AssistantExportFile } from "../types";
import { ExportFileLink } from "./AssistantExportFiles";
import { appendExportLinks, exportDownloadPath } from "./assistantExportLinks.mjs";

type MarkdownMessageProps = {
  content: string;
  print?: boolean;
  files?: AssistantExportFile[];
};

export default function MarkdownMessage({ content, print, files = [] }: MarkdownMessageProps) {
  return (
    <div className="markdown-message min-w-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, () => (tree: Root) => appendExportLinks(tree, files)]}
        skipHtml
        components={{
          a: ({ children, href, node: _node, ...props }) => {
            const file = files.find((item) => exportDownloadPath(item) === href);
            if (file) return <ExportFileLink file={file}>{children}</ExportFileLink>;
            return href?.startsWith("/calls/")
              ? <Link {...props} to={href}>{children}</Link>
              : <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a>;
          },
          ...(print ? { img: () => null } : {}),
          table: ({ children, ...props }) => (
            <div className="my-3 overflow-x-auto">
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
