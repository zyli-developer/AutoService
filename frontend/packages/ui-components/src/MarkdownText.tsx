import type { AnchorHTMLAttributes, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const PLUGINS = [remarkGfm];

const COMPONENTS = {
  a: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

interface MarkdownTextProps {
  children: string;
  className?: string;
  /** Optional render-prop for trailing content (e.g. streaming cursor). */
  trailing?: ReactNode;
}

/**
 * Render a chat message as GitHub-flavored Markdown.
 *
 * The wrapping element always has the `md-text` class so apps can target
 * `.md-text p`, `.md-text ol`, etc. via the shared design-system stylesheet,
 * and add bubble-specific overrides (e.g. dark backgrounds inverting link
 * colors) by combining with their own bubble class.
 */
export function MarkdownText({ children, className, trailing }: MarkdownTextProps) {
  const cls = className ? `md-text ${className}` : 'md-text';
  return (
    <div className={cls} data-testid="md-text">
      <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
      {trailing}
    </div>
  );
}
