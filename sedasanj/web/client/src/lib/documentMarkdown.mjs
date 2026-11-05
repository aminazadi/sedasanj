import MarkdownIt from "markdown-it";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const markdown = new MarkdownIt({ html: false, breaks: false, linkify: false });
const converter = new TurndownService({ headingStyle: "atx", bulletListMarker: "-", codeBlockStyle: "fenced" });
converter.use(gfm);
converter.addRule("strikethrough", {
  filter: ["del", "s", "strike"],
  replacement: (content) => `~~${content}~~`,
});

export const documentToHtml = (content) => markdown.render(content);
export const documentToMarkdown = (html) => converter.turndown(html);
