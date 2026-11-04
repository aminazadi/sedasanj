import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";

type MarkdownMessageProps = {
  content: string;
  print?: boolean;
};

export default function MarkdownMessage({ content, print }: MarkdownMessageProps) {
  return (
    <div className="markdown-message min-w-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href, ...props }) => href?.startsWith("/calls/")
            ? <Link {...props} to={href}>{children}</Link>
            : <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a>,
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
