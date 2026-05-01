import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen, RefreshCw } from 'lucide-react';

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

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8 flex items-center gap-3">
        <BookOpen className="w-8 h-8 text-[#8acaff]" />
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Sentinel Documentation</h1>
          <p className="text-slate-400 mt-1 text-sm">Project overview, policy guidelines, and development reference.</p>
        </div>
      </div>

      <div className="bg-[#11151c] p-8 rounded-xl shadow-lg border border-slate-800 min-h-[500px]">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-500">
            <RefreshCw className="w-8 h-8 animate-spin mb-4 text-blue-500" />
            <p>Loading documentation...</p>
          </div>
        ) : (
          <article className="prose prose-invert max-w-none prose-headings:text-slate-100 prose-a:text-[#8acaff] hover:prose-a:text-[#6baae6] prose-code:bg-[#0b0f15] prose-code:text-slate-200 prose-code:border-slate-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none [&_pre]:bg-[#0b0f15] [&_pre]:border [&_pre]:border-slate-800 [&_pre_code]:bg-transparent [&_pre_code]:p-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}