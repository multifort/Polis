"use client";

// P5 场景库：树导航 + 模板货架 + 分类管理（新增/删除 domain/subcategory）。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type SceneCategoryOut, type TemplateOut } from "@/lib/api";

interface SubcategoryGroup {
  key: string;
  label: string;
  items: TemplateOut[];
}

interface DomainGroup {
  key: string;
  label: string;
  count: number;
  subcategories: SubcategoryGroup[];
}

type Selection =
  | { kind: "all" }
  | { kind: "domain"; domain: string }
  | { kind: "subcategory"; domain: string; subcategory: string };

function sourceLabel(source: string): string {
  if (source === "user_saved") return "用户沉淀";
  if (source === "generated") return "生成沉淀";
  return "平台内置";
}

function visibilityLabel(visibility: string): string {
  return visibility === "private" ? "私有" : "公共";
}

function groupTemplates(
  templates: TemplateOut[],
  cats: SceneCategoryOut[],
): DomainGroup[] {
  // 从 scene_category 建 domain/subcategory 标签映射
  const domainLabel: Record<string, string> = {};
  const subLabel: Record<string, string> = {};
  for (const c of cats) {
    if (!domainLabel[c.domain]) domainLabel[c.domain] = c.domain;
    if (c.subcategory) subLabel[c.subcategory] = c.subcategory;
  }

  const domainMap = new Map<string, Map<string, TemplateOut[]>>();
  for (const tpl of templates) {
    const domain = tpl.domain || "未分类";
    const sub = tpl.subcategory || "通用";
    if (!domainMap.has(domain)) domainMap.set(domain, new Map());
    const subMap = domainMap.get(domain)!;
    subMap.set(sub, [...(subMap.get(sub) ?? []), tpl]);
  }

  return [...domainMap.entries()]
    .map(([domain, subMap]) => {
      const scs = [...subMap.entries()]
        .map(([subcategory, items]) => ({
          key: subcategory,
          label: subLabel[subcategory] ?? subcategory,
          items: [...items].sort((a, b) => a.name.localeCompare(b.name, "zh-CN")),
        }))
        .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
      return {
        key: domain,
        label: domainLabel[domain] ?? domain,
        count: scs.reduce((s, g) => s + g.items.length, 0),
        subcategories: scs,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
}

export default function ScenariosPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [cats, setCats] = useState<SceneCategoryOut[]>([]);
  const [selection, setSelection] = useState<Selection>({ kind: "all" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCatForm, setShowCatForm] = useState(false);
  const [newDomain, setNewDomain] = useState("");
  const [newSub, setNewSub] = useState("");
  const [adding, setAdding] = useState(false);
  const [delMsg, setDelMsg] = useState("");

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tmpls, categories] = await Promise.all([
        api.listTemplates(orgId),
        api.listCategories(orgId),
      ]);
      setTemplates(tmpls);
      setCats(categories);
    } catch {
      setError("加载场景库失败");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => groupTemplates(templates, cats), [templates, cats]);
  const filtered = useMemo(
    () =>
      selection.kind === "all"
        ? templates
        : templates.filter((tpl) => {
            const d = tpl.domain || "未分类";
            const s = tpl.subcategory || "通用";
            if (selection.kind === "domain") return d === selection.domain;
            return d === selection.domain && s === selection.subcategory;
          }),
    [selection, templates],
  );
  const privateCount = templates.filter((tpl) => tpl.visibility === "private").length;

  function useScenario(tpl: TemplateOut) {
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(tpl.name)}`);
  }

  async function onAddCat(e: React.FormEvent) {
    e.preventDefault();
    if (!newDomain.trim()) return;
    setAdding(true);
    try {
      await api.createCategory(orgId, {
        domain: newDomain.trim(),
        subcategory: newSub.trim() || null,
      });
      setNewDomain("");
      setNewSub("");
      setShowCatForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增失败");
    } finally {
      setAdding(false);
    }
  }

  async function onDelCat(id: string, label: string) {
    if (!confirm(`确定删除分类「${label}」？`)) return;
    try {
      await api.deleteCategory(orgId, id);
      setDelMsg(`已删除「${label}」`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  // 按 domain 分组的分类（用于管理面板）
  const catGroups = useMemo(() => {
    const map = new Map<string, SceneCategoryOut[]>();
    for (const c of cats) {
      (map.get(c.domain) ?? map.set(c.domain, []).get(c.domain))!.push(c);
    }
    return map;
  }, [cats]);

  return (
    <AppShell orgId={orgId} active="scenarios" breadcrumb="场景库">
      <div className="page-head scenario-head">
        <div>
          <h1 className="page-title big">场景库</h1>
          <p className="muted">按大类与小类浏览模板 · 管理分类 · 从模板一键出图。</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-run" style={{ background: "#fff", color: "#3F51B5", border: "1px solid #3F51B5", boxShadow: "none" }}
            onClick={() => setShowCatForm(!showCatForm)}>
            {showCatForm ? "收起" : "管理分类"}
          </button>
          <button className="btn-run" onClick={() => void load()} disabled={loading}>
            刷新
          </button>
        </div>
      </div>

      {error && <p className="notice" style={{ marginTop: 14 }}>{error}</p>}
      {delMsg && <p className="notice" style={{ marginTop: 14, background: "#e8f5e9", color: "#1b5e20" }}>{delMsg}</p>}

      {/* 分类管理面板 */}
      {showCatForm && (
        <div className="scenario-cat-panel">
          <h3>分类管理</h3>
          <p className="muted" style={{ marginBottom: 12 }}>
            平台内置分类不可删除；仅可删除自建的私有分类。
          </p>
          {/* 新增表单 */}
          <form className="task-create" onSubmit={onAddCat} style={{ marginBottom: 16 }}>
            <input value={newDomain} onChange={(e) => setNewDomain(e.target.value)} placeholder="大类名称，如：采购与供应链" />
            <input value={newSub} onChange={(e) => setNewSub(e.target.value)} placeholder="子类（可选），如：询价比价" />
            <button className="btn-primary" type="submit" disabled={adding}>
              {adding ? "…" : "＋ 新增"}
            </button>
          </form>
          {/* 已有分类列表 */}
          <div className="cat-mgmt-grid">
            {[...catGroups.entries()].map(([domain, items]) => (
              <div className="cat-mgmt-group" key={domain}>
                <div className="cat-mgmt-domain">
                  <strong>{domain}</strong>
                  <span className="cat-mgmt-count">{items.length}</span>
                </div>
                <div className="cat-mgmt-subs">
                  {items.filter((c) => c.subcategory).map((c) => (
                    <span className="cat-mgmt-sub" key={c.id}>
                      {c.subcategory}
                      {c.org_id && (
                        <button className="catalog-del" onClick={() => onDelCat(c.id, `${c.domain} / ${c.subcategory}`)} title="删除">×</button>
                      )}
                    </span>
                  ))}
                  {items.every((c) => !c.subcategory) && <span className="muted" style={{ fontSize: 11 }}>无子类</span>}
                  {/* 仅无子类的大类可删除 */}
                  {items.some((c) => c.org_id && !c.subcategory) && (
                    <button className="btn-mini danger" style={{ marginLeft: 6 }}
                      onClick={() => {
                        const cat = items.find((c) => c.org_id && !c.subcategory);
                        if (cat) onDelCat(cat.id, cat.domain);
                      }}>
                      删除分类
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="scenario-stats">
        <div className="stat"><div className="stat-ico">库</div><div><div className="stat-label">可用场景</div><div className="stat-value">{templates.length}</div></div></div>
        <div className="stat"><div className="stat-ico">类</div><div><div className="stat-label">大类</div><div className="stat-value">{groups.length}</div></div></div>
        <div className="stat"><div className="stat-ico">私</div><div><div className="stat-label">私有沉淀</div><div className="stat-value">{privateCount}</div></div></div>
      </div>

      {loading ? (
        <div className="empty" style={{ marginTop: 12 }}>加载中…</div>
      ) : templates.length === 0 ? (
        <div className="empty" style={{ marginTop: 12 }}>
          还没有可用场景。完成一次运行后，可在工作详情里将满意计划存为模板。
        </div>
      ) : (
        <div className="scenario-layout">
          <aside className="scenario-tree panel">
            <button className={`scenario-tree-root${selection.kind === "all" ? " on" : ""}`}
              onClick={() => setSelection({ kind: "all" })}>
              <span>全部场景</span><span>{templates.length}</span>
            </button>
            <div className="scenario-domain-list">
              {groups.map((domain) => (
                <div className="scenario-domain" key={domain.key}>
                  <button className={`scenario-domain-btn${
                    selection.kind !== "all" && (selection as any).domain === domain.key ? " on" : ""}`}
                    onClick={() => setSelection({ kind: "domain", domain: domain.key })}>
                    <span>{domain.label}</span><span>{domain.count}</span>
                  </button>
                  <div className="scenario-sub-list">
                    {domain.subcategories.map((subcategory) => (
                      <button key={subcategory.key}
                        className={`scenario-sub-btn${
                          selection.kind === "subcategory" &&
                          (selection as any).domain === domain.key &&
                          (selection as any).subcategory === subcategory.key ? " on" : ""}`}
                        onClick={() => setSelection({ kind: "subcategory", domain: domain.key, subcategory: subcategory.key })}>
                        <span>{subcategory.label}</span><span>{subcategory.items.length}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </aside>

          <section className="panel scenario-list-panel">
            <div className="panel-head">
              <div>
                <h2>{selection.kind === "all" ? "全部场景" : selection.kind === "domain" ? (selection as any).domain : `${(selection as any).domain} / ${(selection as any).subcategory}`}</h2>
                <p className="scenario-panel-sub">{filtered.length} 个场景模板</p>
              </div>
            </div>
            <div className="scenario-grid">
              {filtered.map((tpl) => (
                <article className="scenario-card" key={tpl.id}>
                  <div className="scenario-card-top">
                    <div className="scenario-card-icon">{(tpl.domain || "场").slice(0, 1)}</div>
                    <div className="scenario-card-main">
                      <h3 title={tpl.name}>{tpl.name}</h3>
                      <div className="scenario-card-meta">
                        <span>{tpl.domain || "未分类"}</span>
                        <span>{tpl.subcategory || "通用"}</span>
                      </div>
                    </div>
                  </div>
                  <div className="scenario-card-tags">
                    <span className={`scenario-tag ${tpl.visibility === "private" ? "private" : ""}`}>{visibilityLabel(tpl.visibility)}</span>
                    <span className="scenario-tag">{sourceLabel(tpl.source)}</span>
                    <span className="scenario-tag">v{tpl.version}</span>
                  </div>
                  <button className="scenario-use" onClick={() => useScenario(tpl)}>以此场景出图</button>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
