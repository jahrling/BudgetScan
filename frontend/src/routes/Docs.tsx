import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, FileText } from "lucide-react";
import Markdown from "react-markdown";
import { Layout } from "../components/Layout";
import { apiFetch } from "../lib/api";

interface DocEntry {
  slug: string;
  filename: string;
}

interface DocDetail {
  slug: string;
  filename: string;
  content: string;
}

function DocViewer({ slug, onBack }: { slug: string; onBack: () => void }) {
  const { data, isLoading, error } = useQuery<DocDetail>({
    queryKey: ["docs", slug],
    queryFn: () => apiFetch(`/api/docs/${slug}`),
  });

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-sky-600 mb-4"
      >
        <ChevronLeft className="h-4 w-4" />
        All docs
      </button>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {error && (
        <p className="text-sm text-red-600">Failed to load document.</p>
      )}
      {data && (
        <article className="prose prose-sm md:prose-base prose-gray max-w-none bg-white rounded-xl border border-gray-200 p-4 md:p-8 shadow-sm">
          <Markdown>{data.content}</Markdown>
        </article>
      )}
    </div>
  );
}

export default function Docs() {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  const { data: docs, isLoading } = useQuery<DocEntry[]>({
    queryKey: ["docs"],
    queryFn: () => apiFetch("/api/docs"),
  });

  if (activeSlug) {
    return (
      <Layout>
        <DocViewer slug={activeSlug} onBack={() => setActiveSlug(null)} />
      </Layout>
    );
  }

  return (
    <Layout>
      <h1 className="text-lg font-semibold text-gray-900 mb-3">
        Project docs
      </h1>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="h-14 bg-white rounded-xl border border-gray-200 animate-pulse"
            />
          ))}
        </div>
      )}

      {docs && docs.length === 0 && (
        <p className="text-sm text-gray-500">No documents found.</p>
      )}

      <div className="space-y-2">
        {docs?.map((d) => (
          <button
            key={d.slug}
            type="button"
            onClick={() => setActiveSlug(d.slug)}
            className="flex w-full items-center gap-3 bg-white rounded-xl border border-gray-200 px-4 py-3 shadow-sm text-left hover:border-sky-300 transition-colors"
          >
            <FileText className="h-5 w-5 text-gray-400 shrink-0" />
            <span className="text-sm font-medium text-gray-900">
              {d.slug.replace(/_/g, " ")}
            </span>
          </button>
        ))}
      </div>
    </Layout>
  );
}
