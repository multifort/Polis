"use client";

// P5 场景库：可折叠场景树（双击编辑，± 增删）+ 模板货架。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type SceneCategoryOut, type TemplateOut } from "@/lib/api";

interface TreeNode {
  domain: string;
  subcategories: SceneCategoryOut[];
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
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState<{ domain?: string } | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // category id being edited
  const [editName, setEditName] = useState("");
  const [newName, setNewName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => { inputRef.current?.focus(); }, [editing, adding]);

  const tree = useMemo(() => {
    const map = new Map<string, { subs: SceneCategoryOut[]; count: number }>();
    for (const c of cats) {
      if (!map.has(c.domain)) map.set(c.domain, { subs: [], count: 0 });
      if (c.subcategory) map.get(c.domain)!.subs.push(c);
    }
    for (const t of templates) {
      const d = t.domain || "";
      if (d && map.has(d)) map.get(d)!.count++;
    }
    return [...map.entries()]
      .map(([domain, { subs, count }]) => ({ domain, subcategories: subs, templateCount: count }))
      .sort((a, b) => a.domain.localeCompare(b.domain, "zh-CN"));
  }, [cats, templates]);

  const filtered = useMemo(() => {
    if (selection.kind === "all") return templates;
    return templates.filter((t) => {
      const d = t.domain || "";
      const s = t.subcategory || "";
      if (selection.kind === "domain") return d === selection.domain;
      return d === selection.domain && s === selection.subcategory;
    });
  }, [selection, templates]);

  function useScenario(tpl: TemplateOut) {
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(tpl.name)}`);
  }

  function toggleCollapse(domain: string) {
    setCollapsed((prev) => { const s = new Set(prev); s.has(domain) ? s.delete(domain) : s.add(domain); return s; });
  }

  // 新增
  async function onAdd(domain: string, subcategory?: string) {
    const name = newName.trim();
    if (!name) return;
    try {
      await api.createCategory(orgId, { domain: domain || name, subcategory: subcategory || null });
      setNewName(""); setAdding(null);
      if (domain) setCollapsed((prev) => { const s = new Set(prev); s.delete(domain); return s; }); // 展开以显示新增子类
      await load();
    } catch (err) { setNotice(err instanceof Error ? err.message : "新增失败"); }
  }

  // 删除
  async function onDelete(id: string, label: string) {
    if (!confirm(`删除「${label}」？`)) return;
    try { await api.deleteCategory(orgId, id); await load(); }
    catch (err) { setNotice(err instanceof Error ? err.message : "删除失败"); }
  }

  // 双击开始编辑
  function startEdit(cat: SceneCategoryOut) {
    setEditing(cat.id);
    setEditName(cat.subcategory || cat.domain);
  }

  // 提交编辑
  async function submitEdit(cat: SceneCategoryOut) {
    const name = editName.trim();
    if (!name || name === (cat.subcategory || cat.domain)) { setEditing(null); return; }
    try {
      if (cat.subcategory) {
        await api.updateCategory(orgId, cat.id, { domain: cat.domain, subcategory: name });
      } else {
        await api.updateCategory(orgId, cat.id, { domain: name, subcategory: null });
      }
      setEditing(null);
      await load();
    } catch (err) { setNotice(err instanceof Error ? err.message : "更新失败"); }
  }

  const hasSub = (domain: string) => cats.some((c) => c.domain === domain && c.subcategory);
  const canDel = (cat: SceneCategoryOut) => !!cat.org_id;

  return (
    <AppShell orgId={orgId} active="scenarios" breadcrumb="场景库">
      <div className="page-head scenario-head">
        <div>
          <h1 className="page-title big">场景库</h1>
          <p className="muted">场景树管理分类（双击编辑，± 增删）· 从模板一键出图。</p>
        </div>
      </div>

      {notice && <p className="notice" style={{ marginTop: 14 }}>{notice}</p>}

      {loading ? <div className="empty">加载中…</div> : (
        <div className="scenario-layout">
          {/* 左侧场景树 */}
          <aside className="scenario-tree panel">
            {/* 全部场景 */}
            <button className={`scenario-tree-root${selection.kind === "all" ? " on" : ""}`}
              onClick={() => setSelection({ kind: "all" })}>
              <span>全部场景</span><span>{templates.length}</span>
            </button>

            <div className="scenario-domain-list">
              {tree.map((node) => (
                <div className="scenario-domain" key={node.domain}>
                  {/* Domain 行：点击展开/折叠 + 选中 + ±按钮 */}
                  <div className="scenario-domain-row">
                    <button
                      className={`scenario-domain-btn${selection.kind !== "all" && selection.domain === node.domain ? " on" : ""}`}
                      onClick={() => { toggleCollapse(node.domain); setSelection({ kind: "domain", domain: node.domain }); }}>
                      <span className="scenario-tree-arrow">{collapsed.has(node.domain) ? "▸" : "▾"}</span>
                      {editing && cats.find((c) => c.domain === node.domain && !c.subcategory)?.id === editing ? (
                        <input ref={inputRef} value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onBlur={() => { const cat = cats.find((c) => c.domain === node.domain && !c.subcategory); if (cat) submitEdit(cat); }}
                          onKeyDown={(e) => { if (e.key === "Enter") { const cat = cats.find((c) => c.domain === node.domain && !c.subcategory); if (cat) submitEdit(cat); } }}
                          onClick={(e) => e.stopPropagation()}
                          className="scenario-edit-input" />
                      ) : (
                        <span onDoubleClick={(e) => { e.stopPropagation(); const cat = cats.find((c) => c.domain === node.domain && !c.subcategory); if (cat && canDel(cat)) startEdit(cat); }}>
                          {node.domain}
                        </span>
                      )}
                    </button>
                    <div className="scenario-domain-actions">
                      <button className="scenario-tree-add" title="添加子类"
                        onClick={(e) => { e.stopPropagation(); setAdding({ domain: node.domain }); setNewName(""); }}>
                        ＋
                      </button>
                      {canDel(cats.find((c) => c.domain === node.domain && !c.subcategory)!) && (
                        <button className="scenario-tree-del" title="删除"
                          onClick={(e) => {
                            e.stopPropagation();
                            const cat = cats.find((c) => c.domain === node.domain && !c.subcategory);
                            if (cat) onDelete(cat.id, node.domain);
                          }}>−</button>
                      )}
                    </div>
                  </div>

                  {/* 内联添加子类 */}
                  {adding?.domain === node.domain && (
                    <div className="scenario-inline-add">
                      <input ref={inputRef} value={newName} onChange={(e) => setNewName(e.target.value)}
                        placeholder="子类名称"
                        onKeyDown={(e) => e.key === "Enter" && onAdd(node.domain, newName)} />
                      <button className="btn-mini primary" onClick={() => onAdd(node.domain, newName)}>确定</button>
                      <button className="btn-mini ghost" onClick={() => setAdding(null)}>取消</button>
                    </div>
                  )}

                  {/* 子类列表（可折叠） */}
                  {!collapsed.has(node.domain) && node.subcategories.length > 0 && (
                    <div className="scenario-sub-list">
                      {node.subcategories.map((sub) => (
                        <div className="scenario-sub-row" key={sub.id}>
                          {editing === sub.id ? (
                            <input ref={inputRef} value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              onBlur={() => submitEdit(sub)}
                              onKeyDown={(e) => { if (e.key === "Enter") submitEdit(sub); }}
                              className="scenario-edit-input" />
                          ) : (
                            <button
                              className={`scenario-sub-btn${
                                selection.kind === "subcategory" &&
                                selection.domain === node.domain &&
                                selection.subcategory === sub.subcategory ? " on" : ""}`}
                              onClick={() => setSelection({ kind: "subcategory", domain: node.domain, subcategory: sub.subcategory! })}
                              onDoubleClick={(e) => { e.stopPropagation(); if (canDel(sub)) startEdit(sub); }}>
                              <span>{sub.subcategory}</span>
                            </button>
                          )}
                          {canDel(sub) && (
                            <button className="scenario-tree-del" title="删除"
                              onClick={() => onDelete(sub.id, `${node.domain} / ${sub.subcategory}`)}>−</button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {!collapsed.has(node.domain) && !hasSub(node.domain) && (
                    <div className="scenario-sub-empty">暂无子类，点 ＋ 添加</div>
                  )}
                </div>
              ))}

              {/* 底部：新增大类 */}
              {adding && !adding.domain ? (
                <div className="scenario-inline-add">
                  <input ref={inputRef} value={newName} onChange={(e) => setNewName(e.target.value)}
                    placeholder="新增大类名称"
                    onKeyDown={(e) => e.key === "Enter" && onAdd(newName)} />
                  <button className="btn-mini primary" onClick={() => onAdd(newName)}>确定</button>
                  <button className="btn-mini ghost" onClick={() => setAdding(null)}>取消</button>
                </div>
              ) : (
                <button className="scenario-tree-add-root" onClick={() => { setAdding({}); setNewName(""); }}>
                  ＋ 新增大类
                </button>
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
