import { useState, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import GithubSlugger from 'github-slugger';
import { BookOpen, RefreshCw, List } from 'lucide-react';

export default function QuickReference() {
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v1/readme')
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load README');
        return res.json();
      })
      .then((data) => {
        setContent(data.content);
        setLoading(false);
      })
      .catch((error) => {
        console.error(error);
        setContent('# Error\nFailed to load documentation. Ensure the README.md file exists at the project root.');
        setLoading(false);
      });
  }, []);

  // Derived from the document rather than stored beside it. Holding this in
  // state meant every load rendered once with an empty outline and again with
  // the real one, and left two things that could disagree about the same
  // markdown.
  const headings = useMemo(() => {
    if (!content) return [];

    const extractedHeadings: { id: string; text: string; level: number }[] = [];
    const lines = content.split('\n');
    const slugger = new GithubSlugger();

    let inCodeBlock = false;

    for (const line of lines) {
      if (line.trim().startsWith('```')) {
        inCodeBlock = !inCodeBlock;
        continue;
      }

      if (!inCodeBlock) {
        const match = line.match(/^(#{1,3})\s+(.+)$/);
        if (match) {
          const level = match[1].length;
          // Remove markdown links or other formatting from heading text for display
          const rawText = match[2].trim();
          const text = rawText.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[`*_*~]/g, '');

          // Generate slug based on the text that will be displayed
          // This matches how rehype-slug generates IDs for the rendered HTML
          const slug = slugger.slug(text);

          extractedHeadings.push({
            level,
            text,
            id: slug
          });
        }
      }
    }

    return extractedHeadings;
  }, [content]);

  const scrollToHeading = (id: string, text: string) => {
    // Try to find the element by ID
    let element = document.getElementById(id);
    
    // If not found, try to find it by looking for h1, h2, h3 tags with matching text
    // This is a fallback in case rehype-slug generates different IDs than github-slugger
    if (!element) {
      // Create a slugger instance just for this check to match how rehype-slug might do it
      const slugger = new GithubSlugger();
      const fallbackId = slugger.slug(text);
      element = document.getElementById(fallbackId);
      
      if (!element) {
        const headings = Array.from(document.querySelectorAll('h1, h2, h3'));
        element = headings.find(h => 
          h.id === id || 
          h.id === fallbackId ||
          h.getAttribute('data-heading-text') === text ||
          h.textContent === text || 
          h.textContent?.toLowerCase().replace(/[^a-z0-9]+/g, '-') === id ||
          h.textContent?.includes(text)
        ) as HTMLElement | null;
      }
    }

    if (element) {
      // Use scrollIntoView which is more reliable
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      
      // Also update the URL hash without scrolling
      window.history.pushState(null, '', `#${id}`);
    } else {
      console.warn(`Could not find heading with id: ${id} or text: ${text}`);
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      <div className="mb-8 flex items-center gap-3">
        <BookOpen className="w-8 h-8 text-[#8acaff]" />
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Sentinel Documentation</h1>
          <p className="text-slate-400 mt-1 text-sm">Project overview, policy guidelines, and development reference.</p>
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-6 items-start">
        {/* Sidebar Navigation */}
        <div className="w-full md:w-64 shrink-0 md:sticky md:top-6 bg-[#11151c] p-5 rounded-xl shadow-lg border border-slate-800 hidden md:block max-h-[calc(100vh-48px)] overflow-y-auto">
          <div className="flex items-center gap-2 mb-4 text-slate-200 font-semibold border-b border-slate-800 pb-3 sticky top-0 bg-[#11151c] z-10">
            <List className="w-4 h-4" />
            <h3>Chapters</h3>
          </div>
          
          {loading ? (
            <div className="animate-pulse space-y-3">
              <div className="h-3 bg-slate-800 rounded w-3/4"></div>
              <div className="h-3 bg-slate-800 rounded w-1/2 ml-4"></div>
              <div className="h-3 bg-slate-800 rounded w-5/6"></div>
              <div className="h-3 bg-slate-800 rounded w-2/3 ml-4"></div>
              <div className="h-3 bg-slate-800 rounded w-3/4"></div>
            </div>
          ) : (
            <nav className="space-y-1.5 pb-4">
              {headings.map((heading, idx) => (
                <button
                  key={`${heading.id}-${idx}`}
                  onClick={() => scrollToHeading(heading.id, heading.text)}
                  className={`block w-full text-left text-sm hover:text-[#8acaff] transition-colors truncate ${
                    heading.level === 1 ? 'font-medium text-slate-300 mt-4 first:mt-0' : 
                    heading.level === 2 ? 'text-slate-400 pl-3' : 
                    'text-slate-500 pl-6 text-xs'
                  }`}
                  title={heading.text}
                >
                  {heading.text}
                </button>
              ))}
            </nav>
          )}
        </div>

        {/* Main Content */}
        <div className="flex-1 w-full bg-[#11151c] p-6 md:p-10 rounded-xl shadow-lg border border-slate-800 min-h-[500px] overflow-hidden">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-500">
              <RefreshCw className="w-8 h-8 animate-spin mb-4 text-[#8acaff]" />
              <p>Loading documentation...</p>
            </div>
          ) : (
            <article className="prose prose-invert max-w-none prose-headings:text-slate-100 prose-headings:scroll-mt-6 prose-a:text-[#8acaff] hover:prose-a:text-[#6baae6] prose-code:bg-[#0b0f15] prose-code:text-slate-200 prose-code:border-slate-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none [&_pre]:bg-[#0b0f15] [&_pre]:border [&_pre]:border-slate-800 [&_pre_code]:bg-transparent [&_pre_code]:p-0">
              <ReactMarkdown 
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSlug]}
                components={{
                  // `node` is pulled out of props so react-markdown's AST node
                  // is not spread onto the DOM element.
                  h1: ({node: _node, ...props}) => {
                    const text = Array.isArray(props.children) ? props.children.join('') : String(props.children);
                    const cleanText = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[`*_*~]/g, '');
                    const slug = new GithubSlugger().slug(cleanText);
                    return <h1 id={slug} data-heading-text={cleanText} className="scroll-mt-24" {...props} />;
                  },
                  h2: ({node: _node, ...props}) => {
                    const text = Array.isArray(props.children) ? props.children.join('') : String(props.children);
                    const cleanText = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[`*_*~]/g, '');
                    const slug = new GithubSlugger().slug(cleanText);
                    return <h2 id={slug} data-heading-text={cleanText} className="scroll-mt-24" {...props} />;
                  },
                  h3: ({node: _node, ...props}) => {
                    const text = Array.isArray(props.children) ? props.children.join('') : String(props.children);
                    const cleanText = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[`*_*~]/g, '');
                    const slug = new GithubSlugger().slug(cleanText);
                    return <h3 id={slug} data-heading-text={cleanText} className="scroll-mt-24" {...props} />;
                  },
                }}
              >
                {content}
              </ReactMarkdown>
            </article>
          )}
        </div>
      </div>
    </div>
  );
}