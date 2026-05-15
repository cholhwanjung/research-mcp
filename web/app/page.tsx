"use client";

import { useEffect, useRef, useState } from "react";

import { ChatStream } from "@/components/ChatStream";
import { ModelPicker } from "@/components/ModelPicker";
import { TokenInput } from "@/components/TokenInput";
import { MODELS } from "@/lib/api";
import { useChat } from "@/lib/useChat";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [model, setModel] = useState(MODELS[0].value);
  const [token, setToken] = useState("");
  const [input, setInput] = useState("");
  const { messages, streaming, send } = useChat({
    apiUrl: API_URL,
    token: token || undefined,
    model,
  });
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setToken(localStorage.getItem("research_api_token") ?? "");
  }, []);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const onToken = (v: string) => {
    setToken(v);
    localStorage.setItem("research_api_token", v);
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input;
    setInput("");
    void send(t);
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">
      <header className="flex items-center justify-between gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h1 className="font-semibold">Research Agent</h1>
        <div className="flex items-center gap-2">
          <ModelPicker value={model} onChange={setModel} />
          <TokenInput value={token} onChange={onToken} />
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <p className="mt-20 text-center text-zinc-400">
            논문을 검색하거나 &ldquo;BLIP-2 위키에 추가해줘&rdquo;처럼 요청해 보세요.
            <br />
            노트·그래프는 Obsidian에서 확인합니다.
          </p>
        ) : (
          <ChatStream messages={messages} streaming={streaming} />
        )}
        <div ref={bottomRef} />
      </main>

      <form
        onSubmit={submit}
        className="flex gap-2 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={streaming}
          placeholder="메시지를 입력하세요…"
          className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="rounded-md bg-zinc-900 px-4 py-2 text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-black"
        >
          {streaming ? "…" : "전송"}
        </button>
      </form>
    </div>
  );
}
