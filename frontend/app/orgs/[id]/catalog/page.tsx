"use client";

// P5 场景库管理：分类（domain + subcategory）的查看、新增、删除。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type SceneCategoryOut } from "@/lib/api";

export default function CatalogPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [cats, setCats] = useState<SceneCategoryOut[]>([]);
  const [domain, setDomain] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const load = useCallback(async () => {
    try { setCats(await api.listCategories(orgId)); } catch { setNotice("加载失败"); }
  }, [orgId]);

  useEffect(() => { void load(); }, [load]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!domain.trim()) return;
    setAdding(true); setNotice("");
    try {
      await api.createCategory(orgId, { domain: domain.trim(), subcategory: subcategory.trim() || null });
      setDomain(""); setSubcategory("");
      await load();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "新增失败");
    } finally { setAdding(false); }
  }

  async function onDelete(id: string) {
    try {
      await api.deleteCategory(orgId, id);
      await load();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "删除失败");
    }
  }

  // 按 domain 分组
  const grouped: Record<string, SceneCategoryOut[]> = {};
  for (const c of cats) {
    (grouped[c.domain] ??= []).push(c);
  }

  return (
    <AppShell orgId={orgId} active="work" breadcrumb="场景库">
      <div className="page-head">
        <div>
          <h1 className="page-title big">场景库</h1>
          <p className="muted">管理场景分类（大类 ▸ 子类），保存模板时可选对应分类。</p>
        </div>
      </div>

      {/* 新增分类 */}
      <form className="task-create" onSubmit={onAdd}>
        <input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="大类名称，如：采购与供应链" />
        <input value={subcategory} onChange={(e) => setSubcategory(e.target.value)} placeholder="子类（可选），如：询价比价" />
        <button className="btn-primary" type="submit" disabled={adding}>{adding ? "…" : "＋ 新增分类"}</button>
      </form>

      {notice && <p className="notice" style={{ marginTop: 14 }}>{notice}</p>}

      {/* 分类列表 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 8 }}>
        {Object.entries(grouped).map(([dom, items]) => (
          <div className="catalog-group" key={dom}>
            <h3 className="catalog-domain">{dom}</h3>
            <div className="catalog-subs">
              {items.filter((c) => c.subcategory).map((c) => (
                <span className="catalog-sub" key={c.id}>
                  {c.subcategory}
                  {c.org_id && (
                    <button className="catalog-del" onClick={() => onDelete(c.id)} title="删除">×</button>
                  )}
                </span>
              ))}
              {items.filter((c) => c.subcategory).length === 0 && (
                <span className="muted" style={{ fontSize: 12 }}>（无子类）</span>
              )}
              {/* 删除大类按钮（仅私有） */}
              {items.some((c) => c.org_id && !c.subcategory) && (
                <button
                  className="btn-mini danger"
                  style={{ marginLeft: 8 }}
                  onClick={() => {
                    const cat = items.find((c) => c.org_id && !c.subcategory);
                    if (cat) onDelete(cat.id);
                  }}
                >
                  删除此分类
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
