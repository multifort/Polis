"use client";

// TD-034：公司技能库。提交私有 manual Skill 草稿，经审批后进入编配可用能力。
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type SkillRow } from "@/lib/api";

type StatusFilter = "all" | "draft" | "published";

const STATUS_LABEL: Record<string, string> = {
  draft: "待审核",
  published: "已发布",
  deprecated: "已停用",
};

const TRUST_LABEL: Record<string, string> = {
  official: "官方",
  verified: "人审",
  community: "机审",
  private: "私有",
};

function pillClass(status: string) {
  if (status === "published") return "done";
  if (status === "draft") return "waiting_human";
  return "pending";
}

export default function SkillsPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [mineOnly, setMineOnly] = useState(true);
  const [name, setName] = useState("");
  const [capability, setCapability] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await api.listSkills(orgId, {
        status: status === "all" ? undefined : status,
        mineOnly,
      });
      setSkills(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载技能失败");
    } finally {
      setLoading(false);
    }
  }, [mineOnly, orgId, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    return {
      total: skills.length,
      draft: skills.filter((s) => s.status === "draft").length,
      published: skills.filter((s) => s.status === "published").length,
    };
  }, [skills]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const cleanName = name.trim();
    const cleanCapability = capability.trim();
    const cleanContent = content.trim();
    if (!cleanName || !cleanCapability || cleanContent.length < 20) return;

    setBusy(true);
    setNotice("");
    setError("");
    try {
      await api.createSkill(orgId, {
        name: cleanName,
        capability: cleanCapability,
        content: cleanContent,
      });
      setName("");
      setCapability("");
      setContent("");
      setStatus("draft");
      setMineOnly(true);
      setNotice("技能草稿已提交");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交技能失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell orgId={orgId} active="skills" breadcrumb="技能库">
      <div className="page-head skill-head">
        <div>
          <h1 className="page-title big">技能库</h1>
          <p className="muted">
            {counts.total} 个技能 · {counts.published} 个已发布 · {counts.draft} 个待审核
          </p>
        </div>
        <Link className="btn-mini ghost" href={`/orgs/${orgId}`}>
          审批收件箱
        </Link>
      </div>

      {(notice || error) && (
        <p className={error ? "error" : "notice"} style={{ marginTop: 10 }}>
          {error || notice}
        </p>
      )}

      <div className="skill-layout">
        <section className="panel skill-form-panel">
          <div className="panel-head">
            <h2>提交技能</h2>
          </div>
          <form className="skill-form" onSubmit={submit}>
            <label>
              <span>技能名</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="manual.supplier.delivery"
                autoComplete="off"
              />
            </label>
            <label>
              <span>能力 key</span>
              <input
                value={capability}
                onChange={(e) => setCapability(e.target.value)}
                placeholder="procurement.delivery_review"
                autoComplete="off"
              />
            </label>
            <label>
              <span>Playbook</span>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="步骤1：..."
              />
            </label>
            <button
              className="btn-primary"
              type="submit"
              disabled={busy || !name.trim() || !capability.trim() || content.trim().length < 20}
            >
              {busy ? "提交中…" : "提交草稿"}
            </button>
          </form>
        </section>

        <section className="skill-list-section">
          <div className="skill-toolbar">
            <div className="seg">
              {(["all", "draft", "published"] as StatusFilter[]).map((key) => (
                <button
                  key={key}
                  className={status === key ? "on" : ""}
                  onClick={() => setStatus(key)}
                  type="button"
                >
                  {key === "all" ? "全部" : STATUS_LABEL[key]}
                </button>
              ))}
            </div>
            <label className="skill-toggle">
              <input
                type="checkbox"
                checked={mineOnly}
                onChange={(e) => setMineOnly(e.target.checked)}
              />
              <span>只看本公司</span>
            </label>
          </div>

          <div className="skill-table-wrap">
            <div className="skill-table-head">
              <span>技能</span>
              <span>能力</span>
              <span>信任</span>
              <span>状态</span>
            </div>
            {loading ? (
              <div className="empty">加载中…</div>
            ) : skills.length === 0 ? (
              <div className="empty">暂无技能</div>
            ) : (
              skills.map((skill) => (
                <div className="skill-row" key={skill.id}>
                  <div className="skill-main">
                    <div className="skill-name">
                      <span>{skill.name}</span>
                      <span className="cap-pill">{skill.kind}</span>
                    </div>
                    <div className="skill-preview">{skill.content_preview || "暂无摘要"}</div>
                  </div>
                  <div className="skill-cap mono">{skill.capability || "未绑定"}</div>
                  <div className="skill-trust">{TRUST_LABEL[skill.trust] ?? skill.trust}</div>
                  <div className="skill-status">
                    <span className={`pill ${pillClass(skill.status)}`}>
                      {STATUS_LABEL[skill.status] ?? skill.status}
                    </span>
                    {skill.review_status === "pending" && (
                      <span className="skill-review">待审批</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
