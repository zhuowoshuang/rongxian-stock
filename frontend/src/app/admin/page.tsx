"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAdminStats, getAdminUsers, updateAdminUser, disableAdminUser, getAdminTables, getAdminTableData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import GlassCard from "@/components/ui/GlassCard";
import { SkeletonCard } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import { Shield, Users, Database, BarChart3, AlertCircle, CheckCircle } from "lucide-react";

interface AdminStats {
  total_stocks: number;
  total_signals: number;
  total_users: number;
  total_reports: number;
  total_research_reports: number;
  db_size: string;
}

interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface TableInfo {
  name: string;
  row_count: number;
}

interface TableData {
  columns: string[];
  total: number;
  page: number;
  page_size: number;
  data: Record<string, any>[];
}

export default function AdminPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const router = useRouter();

  // 权限守卫：非管理员重定向到首页
  useEffect(() => {
    if (user && user.role !== "admin") {
      router.replace("/dashboard");
    }
  }, [user, router]);

  if (!user || user.role !== "admin") {
    return <div className="flex items-center justify-center min-h-screen text-dark-muted">{t("common.loading")}</div>;
  }
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [tableData, setTableData] = useState<TableData | null>(null);
  const [tablePage, setTablePage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([
      getAdminStats().then(setStats),
      getAdminUsers().then(setUsers),
      getAdminTables().then(setTables),
    ]).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const handleRoleToggle = async (user: AdminUser) => {
    const newRole = user.role === "admin" ? "user" : "admin";
    try {
      await updateAdminUser(user.id, { role: newRole });
      setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, role: newRole } : u));
      setMsg({ type: "ok", text: `${user.username} → ${newRole}` });
    } catch (e: any) {
      setMsg({ type: "err", text: e.message || "操作失败" });
    }
  };

  const handleActiveToggle = async (user: AdminUser) => {
    try {
      if (user.is_active) {
        await disableAdminUser(user.id);
        setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, is_active: false } : u));
      } else {
        await updateAdminUser(user.id, { is_active: true });
        setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, is_active: true } : u));
      }
      setMsg({ type: "ok", text: `${user.username} ${user.is_active ? "已禁用" : "已启用"}` });
    } catch (e: any) {
      setMsg({ type: "err", text: e.message || "操作失败" });
    }
  };

  const handleSelectTable = async (tableName: string) => {
    setSelectedTable(tableName);
    setTablePage(1);
    setTableLoading(true);
    try {
      const data = await getAdminTableData(tableName, 1, 50);
      setTableData(data);
    } catch (e: any) {
      setMsg({ type: "err", text: e.message || "加载失败" });
    }
    setTableLoading(false);
  };

  const handleTablePage = async (page: number) => {
    if (!selectedTable) return;
    setTablePage(page);
    setTableLoading(true);
    try {
      const data = await getAdminTableData(selectedTable, page, 50);
      setTableData(data);
    } catch (e: any) {
      setMsg({ type: "err", text: e.message || "加载失败" });
    }
    setTableLoading(false);
  };

  if (loading) {
    return (
      <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {[...Array(6)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <span className="w-1 h-6 bg-primary-500 rounded-full" />
        {t("admin.title")}
      </h1>

      {msg && (
        <div className={`px-4 py-3 rounded-xl text-sm flex items-center gap-2 ${
          msg.type === "ok" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
        }`}>
          {msg.type === "ok" ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {msg.text}
        </div>
      )}

      {/* System Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {[
            { label: t("admin.totalStocks"), value: stats.total_stocks.toLocaleString(), icon: <BarChart3 className="w-5 h-5" />, color: "text-primary-400" },
            { label: t("admin.totalSignals"), value: stats.total_signals.toLocaleString(), icon: <BarChart3 className="w-5 h-5" />, color: "text-emerald-400" },
            { label: t("admin.totalUsers"), value: stats.total_users.toLocaleString(), icon: <Users className="w-5 h-5" />, color: "text-blue-400" },
            { label: t("admin.totalReports"), value: stats.total_reports.toLocaleString(), icon: <BarChart3 className="w-5 h-5" />, color: "text-amber-400" },
            { label: t("admin.dbSize"), value: stats.db_size, icon: <Database className="w-5 h-5" />, color: "text-purple-400" },
            { label: t("reports.broker"), value: stats.total_research_reports.toLocaleString(), icon: <BarChart3 className="w-5 h-5" />, color: "text-cyan-400" },
          ].map((m) => (
            <GlassCard key={m.label} className="text-center">
              <div className={`${m.color} mb-2 flex justify-center`}>{m.icon}</div>
              <p className="text-2xl font-bold text-white font-mono">{m.value}</p>
              <p className="text-xs text-dark-muted mt-1">{m.label}</p>
            </GlassCard>
          ))}
        </div>
      )}

      {/* User Management */}
      <GlassCard title={t("admin.userManagement")}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.06]">
                {[t("admin.userId"), t("admin.username"), t("admin.displayName"), t("admin.role"), t("admin.status"), t("admin.createdAt"), t("admin.actions")].map((h) => (
                  <th key={h} className="text-left py-3 px-3 text-dark-muted font-medium text-xs">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-white/[0.03] hover:bg-white/[0.03] transition-colors">
                  <td className="py-3 px-3 font-mono text-xs text-dark-text">{u.id}</td>
                  <td className="py-3 px-3 font-medium text-dark-text">{u.username}</td>
                  <td className="py-3 px-3 text-dark-text">{u.display_name}</td>
                  <td className="py-3 px-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${u.role === "admin" ? "bg-purple-500/10 text-purple-400" : "bg-blue-500/10 text-blue-400"}`}>
                      {u.role === "admin" ? t("sidebar.admin") : t("sidebar.user")}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"}`}>
                      {u.is_active ? t("admin.active") : t("admin.inactive")}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-xs text-dark-muted">{u.created_at?.slice(0, 19)}</td>
                  <td className="py-3 px-3">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleRoleToggle(u)}
                        className="text-xs px-2 py-1 rounded bg-white/[0.05] hover:bg-white/[0.1] text-dark-muted hover:text-white transition-colors"
                      >
                        {u.role === "admin" ? t("admin.makeUser") : t("admin.makeAdmin")}
                      </button>
                      <button
                        onClick={() => handleActiveToggle(u)}
                        className={`text-xs px-2 py-1 rounded transition-colors ${
                          u.is_active
                            ? "bg-red-500/10 text-red-400 hover:bg-red-500/20"
                            : "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                        }`}
                      >
                        {u.is_active ? t("admin.disable") : t("admin.enable")}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Database Browser */}
      <GlassCard title={t("admin.dbBrowser")}>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Table list */}
          <div className="lg:col-span-1 space-y-1 max-h-[500px] overflow-y-auto">
            {tables.map((tbl) => (
              <button
                key={tbl.name}
                onClick={() => handleSelectTable(tbl.name)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-all flex items-center justify-between ${
                  selectedTable === tbl.name
                    ? "bg-primary-500/10 text-primary-400 border border-primary-500/20"
                    : "text-dark-muted hover:bg-white/[0.05] hover:text-dark-text"
                }`}
              >
                <span className="font-mono text-xs">{tbl.name}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.05]">{tbl.row_count}</span>
              </button>
            ))}
          </div>

          {/* Table data */}
          <div className="lg:col-span-3">
            {!selectedTable ? (
              <div className="flex items-center justify-center h-64">
                <EmptyState message={t("admin.selectTable")} />
              </div>
            ) : tableLoading ? (
              <SkeletonCard />
            ) : tableData ? (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-white font-mono">{selectedTable}</h3>
                  <span className="text-xs text-dark-muted">{t("common.total")}: {tableData.total}</span>
                </div>
                <div className="overflow-x-auto max-h-[400px]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-white/[0.06] sticky top-0 bg-dark-card">
                        {tableData.columns.map((col) => (
                          <th key={col} className="text-left py-2 px-2 text-dark-muted font-medium whitespace-nowrap">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tableData.data.map((row, i) => (
                        <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.03]">
                          {tableData.columns.map((col) => (
                            <td key={col} className="py-2 px-2 text-dark-text font-mono whitespace-nowrap max-w-[200px] truncate" title={String(row[col] ?? "")}>
                              {row[col] === null ? <span className="text-dark-muted italic">null</span> : String(row[col])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {tableData.total > tableData.page_size && (
                  <div className="flex justify-center gap-2 mt-4">
                    <button onClick={() => handleTablePage(tablePage - 1)} disabled={tablePage <= 1} className="btn-secondary px-3 py-1.5 text-xs disabled:opacity-40">{t("common.prevPage")}</button>
                    <span className="px-3 py-1.5 text-xs text-dark-muted">{t("admin.page")} {tablePage} / {Math.ceil(tableData.total / tableData.page_size)}</span>
                    <button onClick={() => handleTablePage(tablePage + 1)} disabled={tablePage >= Math.ceil(tableData.total / tableData.page_size)} className="btn-secondary px-3 py-1.5 text-xs disabled:opacity-40">{t("common.nextPage")}</button>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </GlassCard>

      <div className="disclaimer">{t("app.disclaimer")}</div>
    </div>
  );
}
