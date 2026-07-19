"use client";

import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  getSkill,
  listSkills,
  patchSkill,
  putSkill,
  testTrigger,
  type SkillListItem,
} from "@/lib/skills-api";

export default function SkillsPage() {
  const qc = useQueryClient();
  const listQ = useQuery({ queryKey: ["skills"], queryFn: listSkills });
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [openError, setOpenError] = useState<string | null>(null);
  const [testText, setTestText] = useState(
    "Traceback (most recent call last):\n  File \"app.py\", line 1, in <module>\nTypeError: bad",
  );
  const [testResult, setTestResult] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const editorRef = useRef<HTMLElement | null>(null);

  const detailQ = useQuery({
    queryKey: ["skills", selected],
    queryFn: () => getSkill(selected!),
    enabled: Boolean(selected),
  });

  useEffect(() => {
    if (selected && editorRef.current) {
      editorRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selected]);

  const openSkill = async (name: string) => {
    setSelected(name);
    setSaveMsg(null);
    setOpenError(null);
    try {
      const detail = await getSkill(name);
      setDraft(detail.raw_markdown || detail.body);
    } catch (e) {
      setOpenError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveMut = useMutation({
    mutationFn: () => putSkill(selected!, draft),
    onSuccess: () => {
      setSaveMsg("已保存");
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (e: Error) => setSaveMsg(e.message),
  });

  const toggleMut = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      patchSkill(name, { enabled }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["skills"] }),
  });

  const onTest = async () => {
    setTestResult(null);
    try {
      const res = await testTrigger(testText);
      setTestResult(
        `将激活: ${res.active.join(", ") || "（无）"}\n匹配: ${
          res.matches.map((m) => `${m.name}(${m.score.toFixed(2)})`).join(", ") ||
          "无"
        }`,
      );
    } catch (e) {
      setTestResult(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="grid gap-8">
      <section>
        <h2
          className="text-lg font-bold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          技能列表
        </h2>
        <p className="mt-1 text-xs text-[var(--ink-soft)]">
          点击技能名称打开下方编辑器；右侧勾选控制是否启用。
        </p>
        {listQ.isError && (
          <p className="mt-2 text-sm text-[var(--danger)]">
            {(listQ.error as Error).message}
          </p>
        )}
        <ul className="mt-3 divide-y divide-black/8 border border-black/8 bg-white/40">
          {(listQ.data ?? []).map((skill: SkillListItem) => {
            const isSelected = selected === skill.name;
            return (
              <li
                key={skill.name}
                className="flex flex-wrap items-center gap-3 px-3 py-3 text-sm"
                style={{
                  background: isSelected ? "var(--accent-soft)" : undefined,
                }}
              >
                <button
                  type="button"
                  onClick={() => void openSkill(skill.name)}
                  className="min-w-0 flex-1 text-left font-medium underline-offset-2 hover:underline"
                  style={{
                    color: isSelected ? "var(--accent)" : "var(--ink)",
                  }}
                >
                  {skill.name}
                  <span className="mt-0.5 block text-xs font-normal text-[var(--ink-soft)]">
                    {skill.load_strategy} · p{skill.priority} ·{" "}
                    {skill.description || "—"}
                  </span>
                </button>
                <label className="flex items-center gap-1.5 text-xs text-[var(--ink-soft)]">
                  <input
                    type="checkbox"
                    checked={skill.enabled}
                    onChange={(e) =>
                      toggleMut.mutate({
                        name: skill.name,
                        enabled: e.target.checked,
                      })
                    }
                  />
                  启用
                </label>
              </li>
            );
          })}
        </ul>
      </section>

      {selected && (
        <section ref={editorRef}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2
              className="text-lg font-bold text-[var(--ink)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              编辑 · {selected}
            </h2>
            <button
              type="button"
              disabled={saveMut.isPending || detailQ.isLoading}
              onClick={() => saveMut.mutate()}
              className="rounded-full px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              style={{ background: "var(--accent)" }}
            >
              保存
            </button>
          </div>
          {openError && (
            <p className="mb-2 text-sm text-[var(--danger)]">{openError}</p>
          )}
          {saveMsg && (
            <p className="mb-2 text-xs text-[var(--ink-soft)]">{saveMsg}</p>
          )}
          <div className="overflow-hidden border border-black/10 bg-white/70">
            <Editor
              height="420px"
              defaultLanguage="markdown"
              theme="light"
              value={draft}
              onChange={(v) => setDraft(v ?? "")}
              loading={
                <p className="p-4 text-sm text-[var(--ink-soft)]">
                  编辑器加载中…
                </p>
              }
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                wordWrap: "on",
                scrollBeyondLastLine: false,
              }}
            />
          </div>
        </section>
      )}

      <section>
        <h2
          className="text-lg font-bold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          测试触发
        </h2>
        <p className="mt-1 text-xs text-[var(--ink-soft)]">
          下面框里是<strong>模拟用户输入</strong>（不是页面报错）。点「测试」看会激活哪些
          skill。
        </p>
        <textarea
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          rows={4}
          className="mt-2 w-full border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="button"
          onClick={() => void onTest()}
          className="mt-2 rounded-full px-4 py-2 text-sm font-semibold text-white"
          style={{ background: "var(--accent)" }}
        >
          测试
        </button>
        {testResult && (
          <pre className="mt-2 whitespace-pre-wrap text-xs text-[var(--ink-soft)]">
            {testResult}
          </pre>
        )}
      </section>
    </div>
  );
}
