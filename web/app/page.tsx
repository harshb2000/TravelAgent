"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Circle, FileText, LoaderCircle, Moon, Send, Sun } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui-button";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
type Message = { role: "user" | "assistant"; content: string };
type Progress = { entry_id: string; level: number; status: "pending" | "resolved"; label: string; parent_id: string | null };
type Artifact = { id: string; name: string; content?: string };

async function api<T>(path: string, sessionId: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Session-ID": sessionId, ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      message = JSON.parse(text).detail || text;
    } catch {
      // FastAPI may return plain text for unhandled errors.
    }
    throw new Error(message || "Request failed");
  }
  return response.json();
}

function useProgress(sessionId: string) {
  const [items, setItems] = useState<Progress[]>([]);
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    async function connect() {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(`${API}/api/events`, { headers: { "X-Session-ID": sessionId }, signal: controller.signal });
          if (!response.ok || !response.body) throw new Error("Progress unavailable");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split("\n\n");
            buffer = blocks.pop() || "";
            for (const block of blocks) {
              const data = block.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
              if (!data) continue;
              const event = JSON.parse(data) as Progress;
              setItems((old) => {
                const index = old.findIndex((item) => item.entry_id === event.entry_id);
                if (index < 0) return [...old, event];
                if (old[index].status === "resolved" && event.status === "pending") return old;
                const next = [...old];
                next[index] = event;
                return next;
              });
            }
          }
          if (!controller.signal.aborted) await new Promise((resolve) => setTimeout(resolve, 500));
        } catch {
          if (!controller.signal.aborted) await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    }
    connect();
    return () => controller.abort();
  }, [sessionId]);
  return items;
}

function ProgressRow({ item }: { item: Progress }) {
  const resolved = item.status === "resolved";
  return <div data-testid={`progress-${item.entry_id}`} className="flex flex-1 items-center gap-2 py-1.5 text-sm">
    {resolved ? <Check className="h-4 w-4 text-emerald-600" /> : <LoaderCircle className="h-4 w-4 animate-spin text-sky-600" />}
    <span className={resolved ? "text-slate-500 dark:text-slate-400" : "text-slate-800 dark:text-slate-200"}>{item.label}</span>
    <span className="sr-only">{resolved ? "Complete" : "Pending"}</span>
  </div>;
}

function ProgressGroup({ parent, childItems }: { parent: Progress; childItems: Progress[] }) {
  const [expanded, setExpanded] = useState(false);
  const resolved = parent.status === "resolved";
  const open = !resolved || expanded;
  const childrenId = `children-${parent.entry_id}`;

  return <div>
    <button type="button" disabled={!resolved} aria-expanded={open} aria-controls={childrenId} onClick={() => setExpanded((value) => !value)} className="flex w-full items-center text-left disabled:cursor-default">
      <ProgressRow item={parent} />
      {childItems.length > 0 && (open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />)}
    </button>
    {open && childItems.length > 0 && <div id={childrenId} data-testid={childrenId} className="ml-6 border-l pl-3">{childItems.map((child) => <ProgressRow key={child.entry_id} item={child} />)}</div>}
  </div>;
}

export default function Home() {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [dark, setDark] = useState(true);
  const [progressCollapsed, setProgressCollapsed] = useState(false);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const progressScrollRef = useRef<HTMLDivElement>(null);
  const progress = useProgress(sessionId);
  const queryClient = useQueryClient();
  useEffect(() => {
    // Browser-only by design: every page load gets an isolated temporary session.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSessionId(crypto.randomUUID());
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
  }, [messages]);
  useEffect(() => {
    if (!progressCollapsed && progressScrollRef.current) progressScrollRef.current.scrollTop = progressScrollRef.current.scrollHeight;
  }, [progress, progressCollapsed]);

  const artifacts = useQuery({
    queryKey: ["artifacts", sessionId],
    queryFn: () => api<Artifact[]>("/api/artifacts", sessionId),
    enabled: Boolean(sessionId),
  });
  const preview = useQuery({
    queryKey: ["artifact", sessionId, selected],
    queryFn: () => api<Artifact>(`/api/artifacts/${encodeURIComponent(selected!)}`, sessionId),
    enabled: Boolean(sessionId && selected),
  });
  const chat = useMutation({
    mutationFn: (message: string) => api<{ response: string }>("/api/chat", sessionId, { method: "POST", body: JSON.stringify({ message }) }),
    onSuccess: ({ response }) => {
      setMessages((old) => [...old, { role: "assistant", content: response }]);
      queryClient.invalidateQueries({ queryKey: ["artifacts", sessionId] });
    },
  });
  const timeline = useMemo(() => {
    const ordered = [...progress].sort((a, b) => Number(a.entry_id.slice(1)) - Number(b.entry_id.slice(1)));
    return ordered
      .filter((item) => item.level === 1 || !item.parent_id)
      .map((item) => ({ item, children: ordered.filter((child) => child.parent_id === item.entry_id) }));
  }, [progress]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || chat.isPending || !sessionId) return;
    setMessages((old) => [...old, { role: "user", content: message }]);
    setDraft("");
    chat.mutate(message);
  }

  return <main className="flex h-dvh overflow-hidden flex-col bg-slate-50 dark:bg-slate-950">
    <header className="flex h-16 shrink-0 items-center justify-between border-b bg-white px-5 dark:border-slate-800 dark:bg-slate-900">
      <div><h1 className="font-semibold">TravelAgent</h1><p className="text-xs text-slate-500 dark:text-slate-400">Temporary session {sessionId.slice(0, 8) || "starting…"}</p></div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400"><Circle className="h-2.5 w-2.5 fill-emerald-500 text-emerald-500" /> In memory</div>
        <Button type="button" variant="ghost" size="icon" onClick={() => setDark((value) => !value)} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
      </div>
    </header>

    <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,18rem)] overflow-hidden md:grid-cols-[minmax(0,1fr)_360px] md:grid-rows-1">
      <section className="flex min-h-0 flex-col overflow-hidden">
        <div ref={chatScrollRef} data-testid="chat-scroll" className="flex-1 overflow-y-auto p-5 md:p-8">
          {messages.length === 0 && <div className="mx-auto mt-20 max-w-xl text-center"><h2 className="text-3xl font-semibold tracking-tight">Where should we go?</h2><p className="mt-3 text-slate-500 dark:text-slate-400">Share your destination, dates, budget, or just the kind of trip you want.</p></div>}
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.map((message, index) => <article key={index} className={message.role === "user" ? "ml-auto max-w-[85%] rounded-2xl bg-sky-600 px-4 py-3 text-white" : "markdown max-w-none rounded-2xl border bg-white px-5 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900"}>
              {message.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown> : message.content}
            </article>)}
            {chat.isError && <p role="alert" className="text-sm text-red-600">{chat.error.message}</p>}
          </div>
        </div>
        <div data-testid="chat-footer" className="shrink-0 border-t bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="mx-auto max-w-3xl">
            {(chat.isPending || progress.length > 0) && <div className="mb-3 rounded-xl border dark:border-slate-700" aria-label="Agent progress">
              <button type="button" aria-expanded={!progressCollapsed} aria-controls="trip-progress" onClick={() => setProgressCollapsed((value) => !value)} className="flex w-full items-center justify-between px-3 py-2 text-left">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{chat.isPending ? "Working on your trip" : "Trip progress"}</span>
                {progressCollapsed ? <ChevronRight className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
              </button>
              {!progressCollapsed && <div ref={progressScrollRef} id="trip-progress" className="max-h-32 overflow-y-auto border-t px-3 py-2 dark:border-slate-700">
                {timeline.map(({ item, children }) => item.level === 1
                  ? <ProgressGroup key={item.entry_id} parent={item} childItems={children} />
                  : <ProgressRow key={item.entry_id} item={item} />)}
                {progress.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">Starting…</p>}
              </div>}
            </div>}
            <form onSubmit={submit} className="flex gap-2">
              <label htmlFor="message" className="sr-only">Message</label>
              <textarea id="message" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} rows={2} placeholder="Plan a 7-day trip to Tokyo…" className="min-h-12 flex-1 resize-none rounded-xl border bg-white px-4 py-3 outline-none focus:ring-2 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-950" />
              <Button type="submit" size="icon" className="h-auto w-12" disabled={chat.isPending || !draft.trim()} aria-label="Send message"><Send className="h-4 w-4" /></Button>
            </form>
          </div>
        </div>
      </section>

      <aside className="min-h-0 overflow-y-auto border-l bg-white p-5 dark:border-slate-800 dark:bg-slate-900 max-md:border-l-0 max-md:border-t" aria-label="Artifacts">
        <h2 className="mb-4 font-semibold">Artifacts</h2>
        {!artifacts.data?.length && <p className="text-sm text-slate-500 dark:text-slate-400">Generated plans and reports will appear here.</p>}
        <div className="space-y-2">{artifacts.data?.map((artifact) => <button key={artifact.id} onClick={() => setSelected(artifact.id)} className={`flex w-full items-center gap-2 rounded-lg border p-3 text-left text-sm dark:border-slate-700 ${selected === artifact.id ? "border-sky-500 bg-sky-50 dark:bg-sky-950" : "hover:bg-slate-50 dark:hover:bg-slate-800"}`}><FileText className="h-4 w-4" />{artifact.name}</button>)}</div>
        {preview.data && <article className="markdown mt-5 border-t pt-4 dark:border-slate-700" data-testid="artifact-preview"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.data.content || ""}</ReactMarkdown></article>}
      </aside>
    </div>
  </main>;
}
