"use client";

// P5 场景库树导航：基于 R3 的 domain/subcategory，把可见 plan_template 组织成货架。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, getAccess, type TemplateOut } from "@/lib/api";

const DOMAIN_LABEL: Record<string, string> = {
  procurement: "采购供应",
  report: "报告生成",
  data: "数据分析",
  web: "网页研究",
  uncategorized: "未分类",
};

const SUBCATEGORY_LABEL: Record<string, string> = {
  supplier: "供应商分析",
  rfq: "询价比价",
  spend: "支出分析",
  quality: "质量评估",
  general: "通用场景",
};

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

function labelOf(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}

function sourceLabel(source: string): string {
  if (source === "user_saved") return "用户沉淀";
  if (source === "generated") return "生成沉淀";
  return "平台内置";
}

function visibilityLabel(visibility: string): string {
  return visibility === "private" ? "私有" : "公共";
}

function groupTemplates(templates: TemplateOut[]): DomainGroup[] {
  const domainMap = new Map<string, Map<string, TemplateOut[]>>();
  for (const tpl of templates) {
    const domain = tpl.domain || "uncategorized";
    const subcategory = tpl.subcategory || "general";
    if (!domainMap.has(domain)) domainMap.set(domain, new Map());
    const subMap = domainMap.get(domain)!;
    subMap.set(subcategory, [...(subMap.get(subcategory) ?? []), tpl]);
  }

  return [...domainMap.entries()]
    .map(([domain, subMap]) => {
      const subcategories = [...subMap.entries()]
        .map(([subcategory, items]) => ({
          key: subcategory,
          label: labelOf(SUBCATEGORY_LABEL, subcategory),
          items: [...items].sort((a, b) => a.name.localeCompare(b.name, "zh-CN")),
        }))
        .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
      return {
        key: domain,
        label: labelOf(DOMAIN_LABEL, domain),
        count: subcategories.reduce((sum, g) => sum + g.items.length, 0),
        subcategories,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
}

function matchesSelection(tpl: TemplateOut, selection: Selection): boolean {
  if (selection.kind === "all") return true;
  const domain = tpl.domain || "uncategorized";
  if (selection.kind === "domain") return domain === selection.domain;
  const subcategory = tpl.subcategory || "general";
  return domain === selection.domain && subcategory === selection.subcategory;
}

function selectionTitle(selection: Selection, groups: DomainGroup[]): string {
  if (selection.kind === "all") return "全部场景";
  const domain = groups.find((g) => g.key === selection.domain);
  if (selection.kind === "domain") return domain?.label ?? selection.domain;
  const subcategory = domain?.subcategories.find((g) => g.key === selection.subcategory);
  return `${domain?.label ?? selection.domain} / ${subcategory?.label ?? selection.subcategory}`;
}

export default function ScenariosPage() {
  const router = useRouter();
  const orgId = useParams<{ id: string }>().id;
  const [templates, setTemplates] = useState<TemplateOut[]>([]);
  const [selection, setSelection] = useState<Selection>({ kind: "all" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getAccess()) router.replace("/");
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTemplates(await api.listTemplates(orgId));
    } catch {
      setError("加载场景库失败");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => groupTemplates(templates), [templates]);
  const filtered = useMemo(
    () => templates.filter((tpl) => matchesSelection(tpl, selection)),
    [selection, templates],
  );
  const privateCount = templates.filter((tpl) => tpl.visibility === "private").length;

  function useScenario(tpl: TemplateOut) {
    router.push(`/orgs/${orgId}/plans?goal=${encodeURIComponent(tpl.name)}`);
  }

  return (
    <AppShell orgId={orgId} active="scenarios" breadcrumb="场景库">
      <div className="page-head scenario-head">
        <div>
          <h1 className="page-title big">场景库</h1>
          <p className="muted">按大类与小类浏览可复用模板，把沉淀下来的经验变成下一次工作的入口。</p>
        </div>
        <button className="btn-run" onClick={() => void load()} disabled={loading}>
          刷新
        </button>
      </div>

      {error && <p className="notice" style={{ marginTop: 14 }}>{error}</p>}

      <div className="scenario-stats">
        <div className="stat">
          <div className="stat-ico">库</div>
          <div>
            <div className="stat-label">可用场景</div>
            <div className="stat-value">{templates.length}</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-ico">类</div>
          <div>
            <div className="stat-label">大类</div>
            <div className="stat-value">{groups.length}</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-ico">私</div>
          <div>
            <div className="stat-label">私有沉淀</div>
            <div className="stat-value">{privateCount}</div>
          </div>
        </div>
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
            <button
              className={`scenario-tree-root${selection.kind === "all" ? " on" : ""}`}
              onClick={() => setSelection({ kind: "all" })}
            >
              <span>全部场景</span>
              <span>{templates.length}</span>
            </button>
            <div className="scenario-domain-list">
              {groups.map((domain) => (
                <div className="scenario-domain" key={domain.key}>
                  <button
                    className={`scenario-domain-btn${
                      selection.kind !== "all" && selection.domain === domain.key ? " on" : ""
                    }`}
                    onClick={() => setSelection({ kind: "domain", domain: domain.key })}
                  >
                    <span>{domain.label}</span>
                    <span>{domain.count}</span>
                  </button>
                  <div className="scenario-sub-list">
                    {domain.subcategories.map((subcategory) => (
                      <button
                        key={subcategory.key}
                        className={`scenario-sub-btn${
                          selection.kind === "subcategory" &&
                          selection.domain === domain.key &&
                          selection.subcategory === subcategory.key
                            ? " on"
                            : ""
                        }`}
                        onClick={() =>
                          setSelection({
                            kind: "subcategory",
                            domain: domain.key,
                            subcategory: subcategory.key,
                          })
                        }
                      >
                        <span>{subcategory.label}</span>
                        <span>{subcategory.items.length}</span>
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
                <h2>{selectionTitle(selection, groups)}</h2>
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
                        <span>{labelOf(DOMAIN_LABEL, tpl.domain || "uncategorized")}</span>
                        <span>{labelOf(SUBCATEGORY_LABEL, tpl.subcategory || "general")}</span>
                      </div>
                    </div>
                  </div>
                  <div className="scenario-card-tags">
                    <span className={`scenario-tag ${tpl.visibility === "private" ? "private" : ""}`}>
                      {visibilityLabel(tpl.visibility)}
                    </span>
                    <span className="scenario-tag">{sourceLabel(tpl.source)}</span>
                    <span className="scenario-tag">v{tpl.version}</span>
                  </div>
                  <button className="scenario-use" onClick={() => useScenario(tpl)}>
                    以此场景出图
                  </button>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
