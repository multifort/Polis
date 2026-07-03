"use client";

// P5 场景库：左侧场景树（从 scene_category 构建，可直接增删） + 右侧模板货架。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type SceneCategoryOut, type TemplateOut } from "@/lib/api";

interface TreeNode {
  domain: string;
  subcategories: SceneCategoryOut[]; // subcategory entries for this domain
  templateCount: number;
}

type Selection = { kind: "all" } | { kind: "domain"; domain: string } | { kind: "subcategory"; domain: string; subcategory: string };

function sourceLabel(source: string): string {
  if (source === "user_saved") return "用户沉淀";
  if (source === "generated") return "生成沉淀";
  return "平台内置";
}

export default function ScenariosPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [cats, setCats] = useState<SceneCategoryOut[]>([]);
  const [selection, setSelection] = useState<Selection>({ kind: "all" });
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState<{ domain?: string } | null>(null);
  const [newName, setNewName] = useState("");

  useEffect(() => { if (!getAccess()) router.replace("/"); }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tmpls, categories] = await Promise.all([
        api.listTemplates(orgId),
        api.listCategories(orgId),
      ]);
      setTemplates(tmpls);
      setCats(categories);
    } catch { setNotice("加载失败"); }
    finally { setLoading(false); }
  }, [orgId]);

  useEffect(() => { void load(); }, [load]);

  // 从 scene_category + templates 构建树
  const tree = useMemo(() => {
    // domain → { subcategories, templateCount }
    const map = new Map<string, { subs: SceneCategoryOut[]; count: number }>();
    for (const c of cats) {
      if (!map.has(c.domain)) map.set(c.domain, { subs: [], count: 0 });
      if (c.subcategory) map.get(c.domain)!.subs.push(c);
    }
    // 统计每个 domain 下的模板数
    for (const t of templates) {
      const d = t.domain || "";
      if (d && map.has(d)) map.get(d)!.count++;
    }
    return [...map.entries()]
      .map(([domain, { subs, count }]) => ({ domain, subcategories: subs, templateCount: count }))
      .sort((a, b) => a.domain.localeCompare(b.domain, "zh-CN"));
  }, [cats, templates]);

  // 当前选中分类的模板
  const filtered = useMemo(() => {
    if (selection.kind === "all") return templates;
    return templates.filter((t) => {
      const d = t.domain || "";
      const s = t.subcategory || "";
      if (selection.kind === "domain") return d === selection.domain;
      return d === selection.domain && s === selection.subcategory;
    });
  }, [selection, templates]);

  const totalTemplates = templates.length;
  const privateCount = templates.filter((t) => t.visibility === "private").length;

  function useScenario(tpl: TemplateOut) {
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(tpl.name)}`);
  }

  // 新增 domain 或 subcategory
  async function onAdd(domain: string, subcategory?: string) {
    const name = newName.trim();
    if (!name) return;
    try {
      await api.createCategory(orgId, { domain: domain || name, subcategory: subcategory ? name : null });
      setNewName(""); setAdding(null);
      await load();
    } catch (err) { setNotice(err instanceof Error ? err.message : "新增失败"); }
  }

  async function onDelete(id: string, label: string) {
    if (!confirm(`删除「${label}」？`)) return;
    try {
      await api.deleteCategory(orgId, id);
      await load();
    } catch (err) { setNotice(err instanceof Error ? err.message : "删除失败"); }
  }

  // 检查某个 domain 是否有可删的条目（org_id 非空）
  const canDeleteDomain = (domain: string) =>
    cats.some((c) => c.domain === domain && !c.subcategory && c.org_id);

  return (
    <AppShell orgId={orgId} active="scenarios" breadcrumb="场景库">
      <div className="page-head scenario-head">
        <div>
          <h1 className="page-title big">场景库</h1>
          <p className="muted">左侧树管理分类，右侧浏览模板 · 从模板一键出图。</p>
        </div>
        <button className="btn-run" style={{ background: "#fff", color: "#3F51B5", border: "1px solid #3F51B5", boxShadow: "none" }}
          onClick={() => { setAdding({}); setNewName(""); }}>＋ 新增大类</button>
      </div>

      {notice && <p className="notice" style={{ marginTop: 14 }}>{notice}</p>}

      {loading ? <div className="empty">加载中…</div> : templates.length === 0 && cats.length === 0 ? (
        <div className="empty">还没有场景分类或模板。在左侧树新增大类，或完成运行后存为模板。</div>
      ) : (
        <div className="scenario-layout">
          {/* 左侧场景树 */}
          <aside className="scenario-tree panel">
            <button className={`scenario-tree-root${selection.kind === "all" ? " on" : ""}`}
              onClick={() => setSelection({ kind: "all" })}>
              <span>全部场景</span><span>{totalTemplates}</span>
            </button>
            <div className="scenario-domain-list">
              {tree.map((node) => (
                <div className="scenario-domain" key={node.domain}>
                  <div className="scenario-domain-row">
                    <button
                      className={`scenario-domain-btn${selection.kind !== "all" && selection.domain === node.domain ? " on" : ""}`}
                      onClick={() => setSelection({ kind: "domain", domain: node.domain })}>
                      <span>{node.domain}</span>
                      <span className="scenario-count">{node.templateCount}</span>
                    </button>
                    <div className="scenario-domain-actions">
                      <button className="scenario-tree-add" title="添加子类"
                        onClick={() => { setAdding({ domain: node.domain }); setNewName(""); }}>
                        ＋
                      </button>
                      {canDeleteDomain(node.domain) && (
                        <button className="scenario-tree-del" title="删除此分类"
                          onClick={() => {
                            const cat = cats.find((c) => c.domain === node.domain && !c.subcategory && c.org_id);
                            if (cat) onDelete(cat.id, node.domain);
                          }}>
                          ×
                        </button>
                      )}
                    </div>
                    {/* 内联添加子类输入 */}
                    {adding?.domain === node.domain && (
                      <div className="scenario-inline-add">
                        <input value={newName} onChange={(e) => setNewName(e.target.value)}
                          placeholder="子类名称" autoFocus
                          onKeyDown={(e) => e.key === "Enter" && onAdd(node.domain, newName)} />
                        <button className="btn-mini" onClick={() => onAdd(node.domain, newName)}>确定</button>
                        <button className="btn-mini ghost" onClick={() => setAdding(null)}>取消</button>
                      </div>
                    )}
                  </div>
                  {/* 子类列表 */}
                  {node.subcategories.length > 0 && (
                    <div className="scenario-sub-list">
                      {node.subcategories.map((sub) => (
                        <div className="scenario-sub-row" key={sub.id}>
                          <button
                            className={`scenario-sub-btn${
                              selection.kind === "subcategory" &&
                              selection.domain === node.domain &&
                              selection.subcategory === sub.subcategory ? " on" : ""}`}
                            onClick={() => setSelection({ kind: "subcategory", domain: node.domain, subcategory: sub.subcategory! })}>
                            <span>{sub.subcategory}</span>
                          </button>
                          {sub.org_id && (
                            <button className="scenario-tree-del"
                              onClick={() => onDelete(sub.id, `${node.domain} / ${sub.subcategory}`)} title="删除">×</button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {/* 底部新增根大类 */}
              {adding && !adding.domain && (
                <div className="scenario-inline-add" style={{ marginTop: 8 }}>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)}
                    placeholder="新增大类名称" autoFocus
                    onKeyDown={(e) => e.key === "Enter" && onAdd(newName)} />
                  <button className="btn-mini primary" onClick={() => onAdd(newName)}>确定</button>
                  <button className="btn-mini ghost" onClick={() => setAdding(null)}>取消</button>
                </div>
              )}
            </div>
          </aside>

          {/* 右侧模板列表 */}
          <section className="panel scenario-list-panel">
            <div className="panel-head">
              <div>
                <h2>{selection.kind === "all" ? "全部场景" : selection.kind === "domain" ? selection.domain : `${selection.domain} / ${selection.subcategory}`}</h2>
                <p className="scenario-panel-sub">{filtered.length} 个场景模板</p>
              </div>
            </div>
            {filtered.length === 0 ? (
              <p className="hint" style={{ padding: 14 }}>
                {selection.kind === "all" ? "还没有场景模板。完成运行后将满意计划存为模板即可出现在这里。" : "该分类下暂无模板。"}
              </p>
            ) : (
              <div className="scenario-grid">
                {filtered.map((tpl) => (
                  <article className="scenario-card" key={tpl.id}>
                    <div className="scenario-card-top">
                      <div className="scenario-card-icon">{(tpl.domain || "场").slice(0, 1)}</div>
                      <div className="scenario-card-main">
                        <h3 title={tpl.name}>{tpl.name}</h3>
                        <div className="scenario-card-meta">
                          <span>{tpl.domain || "未分类"}</span>
                          {tpl.subcategory && <span>{tpl.subcategory}</span>}
                        </div>
                      </div>
                    </div>
                    <div className="scenario-card-tags">
                      <span className={`scenario-tag ${tpl.visibility === "private" ? "private" : ""}`}>
                        {tpl.visibility === "private" ? "私有" : "公共"}
                      </span>
                      <span className="scenario-tag">{sourceLabel(tpl.source)}</span>
                      <span className="scenario-tag">v{tpl.version}</span>
                    </div>
                    <button className="scenario-use" onClick={() => useScenario(tpl)}>以此场景出图</button>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}
