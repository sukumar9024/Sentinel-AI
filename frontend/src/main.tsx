import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileText,
  FlaskConical,
  Layers3,
  LayoutDashboard,
  LogOut,
  Search,
  Shield,
  ShieldAlert,
  Terminal,
  X,
} from "lucide-react";
import "./style.css";
import { Operations, IntegrationHealth } from "./Operations";
import { request, setSession, clearSession, ApiError } from "./client";

type User = { username: string; role: string };
type Incident = {
  id: string;
  title: string;
  severity: string;
  status: string;
  service: string;
  source_ip: string;
  first_seen: string;
  last_seen: string;
  owner: string | null;
  resolution?: string;
};
type SecurityEvent = {
  event_id: string;
  timestamp: string;
  event_type: string;
  service: string;
  source_ip: string;
  message: string;
  http_path?: string;
  status_code?: number;
  source_type: string;
};
type Rule = {
  enabled: boolean;
  id: string;
  name: string;
  severity: string;
  count: number;
  within_seconds: number;
  mitre?: { id: string; name: string; tactic: string };
};
type Alert = Rule & { rule_id: string; title: string; event_ids: string[] };
type Detail = Incident & {
  alerts: Alert[];
  events: SecurityEvent[];
  evidence_count: number;
  notes: { id: string; author: string; body: string; created_at: string }[];
  analysis: {
    label: string;
    summary: string;
    investigation_steps: string[];
    recommended_actions: string[];
  };
};
type Dashboard = {
  events: number;
  alerts: number;
  open_incidents: number;
  critical: number;
  high: number;
  queued: number;
  dead_letters: number;
  events_per_second: number;
  services: { name: string; count: number }[];
  activity: number[];
  rules: number;
  demo_enabled: boolean;
  ai_enabled: boolean;
  queue_backend: string;
};
const stamp = (value: string) =>
  new Date(
    value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value + "Z",
  );
const time = (value: string) =>
  stamp(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const fmt = (n: number) => n.toLocaleString();
const label = (s: string) => s.replaceAll("_", " ").toLowerCase();

function App() {
  // Tokens stay in memory, never localStorage; a reload requires reauthentication.
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [page, setPage] = useState("Overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [requestId, setRequestId] = useState("");
  const [searchBackend, setSearchBackend] = useState("database");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [resolution, setResolution] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);
  const api = useCallback(
    async (path: string, options: RequestInit = {}) => {
      try {
        return await (await request(path, options)).json();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401 && token) {
          clearSession();
          setToken("");
          setUser(null);
        }
        throw e;
      }
    },
    [token],
  );
  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const [dash, list, ev, ruleList] = await Promise.all([
        api("/dashboard"),
        api(
          `/incidents?q=${encodeURIComponent(query)}&severity=${severity}&offset=${page === "Incidents" ? offset : 0}`,
        ),
        api(
          `/search?q=${encodeURIComponent(query)}&offset=${page === "Event explorer" ? offset : 0}${startTime ? "&start=" + encodeURIComponent(new Date(startTime).toISOString()) : ""}${endTime ? "&end=" + encodeURIComponent(new Date(endTime).toISOString()) : ""}${requestId ? "&request_id=" + encodeURIComponent(requestId) : ""}`,
        ),
        api("/rules"),
      ]);
      setDashboard(dash);
      setIncidents(list.items);
      setEvents(ev.items);
      setSearchBackend(ev.backend);
      setRules(ruleList.items);
      setTotal(page === "Event explorer" ? ev.total : list.total);
      setUpdated(new Date());
      setError("");
      if (selected) setDetail(await api(`/incidents/${selected}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [
    token,
    api,
    query,
    severity,
    page,
    offset,
    selected,
    startTime,
    endTime,
    requestId,
  ]);
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 4000);
    return () => clearInterval(id);
  }, [refresh]);
  useEffect(() => {
    if (notice) {
      const id = setTimeout(() => setNotice(""), 7000);
      return () => clearTimeout(id);
    }
  }, [notice]);
  async function login(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(e.currentTarget);
    try {
      const data = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      setPage("Overview");
      setQuery("");
      setOffset(0);
      setSession(data);
      setToken(data.access_token);
      setUser(data.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function simulate() {
    setBusy(true);
    try {
      const result = await api("/lab/run", { method: "POST" });
      setNotice(
        `${result.accepted} synthetic events queued. Watch the incident appear as the worker processes them.`,
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function mutate(path: string, method: string, body: object) {
    setBusy(true);
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await refresh();
      if (path.endsWith("/notes")) setNote("");
      setNotice("Investigation updated. Action recorded in the audit log.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const navigate = (next: string) => {
    setPage(next);
    setQuery("");
    setSeverity("");
    setOffset(0);
  };
  const canEdit = user?.role !== "viewer";
  if (!user)
    return (
      <div className="login-screen">
        <div className="login-visual">
          <div className="brand">
            <Shield size={29} /> Sentinel<span>AI</span>
          </div>
          <div className="login-copy">
            <div className="eyebrow">SECURITY, WITH CONTEXT</div>
            <h1>
              From scattered signals.
              <br />
              To a clearer picture.
            </h1>
            <p>
              Follow the evidence. Connect the events.
              <br />
              Investigate what matters.
            </p>
            <div className="pipeline">
              <span>COLLECT</span>
              <ArrowRight size={16} />
              <span>DETECT</span>
              <ArrowRight size={16} />
              <span>INVESTIGATE</span>
            </div>
          </div>
          <div className="login-foot">
            DETERMINISTIC DETECTION <span> / </span> ANALYST-LED RESPONSE
          </div>
        </div>
        <form className="login-form" onSubmit={login}>
          <div className="eyebrow">ANALYST CONSOLE</div>
          <h2>Welcome back</h2>
          <p>Sign in to your security workspace.</p>
          <label>
            Username
            <input
              name="username"
              defaultValue="admin"
              autoComplete="username"
              required
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
            <ArrowRight size={16} />
          </button>
          <div className="login-hint">
            <Terminal size={17} />
            <span>
              Local setup: run <code>python3 scripts/bootstrap.py</code>, then
              use the password in your <code>.env</code> file.
            </span>
          </div>
          <small>SentinelAI · Portfolio lab / v0.2</small>
        </form>
      </div>
    );
  const incidentTable = (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>SEVERITY</th>
            <th>INCIDENT</th>
            <th>SOURCE / ASSET</th>
            <th>STATUS</th>
            <th>LAST OBSERVED</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {incidents.slice(0, page === "Overview" ? 6 : 50).map((i) => (
            <tr
              key={i.id}
              onClick={() => {
                setSelected(i.id);
                setDetail(null);
                setResolution(i.resolution || "");
              }}
            >
              <td>
                <span className={`badge ${i.severity}`}>
                  <i />
                  {i.severity}
                </span>
              </td>
              <td>
                <button className="row-button">{i.title}</button>
                <small className="mono">
                  INC-{i.id.slice(0, 8).toUpperCase()}
                </small>
              </td>
              <td>
                <span className="mono">{i.source_ip || "Host-local"}</span>
                <small>{i.service}</small>
              </td>
              <td>
                <span className={`status ${i.status === "NEW" ? "new" : ""}`}>
                  {label(i.status)}
                </span>
              </td>
              <td className="mono muted">{time(i.last_seen)}</td>
              <td>
                <ChevronRight size={16} className="muted" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!incidents.length && (
        <div className="empty">
          <Shield size={30} />
          <h3>No incidents to investigate</h3>
          <p>
            {query || severity
              ? "Adjust your filters to see more results."
              : "Run the security simulation to send evidence through the pipeline."}
          </p>
        </div>
      )}
    </div>
  );
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Shield size={26} /> Sentinel<span>AI</span>
        </div>
        <div className="workspace">
          <div className="workspace-icon">S</div>
          <div>
            Security workspace<small>Local environment</small>
          </div>
          <span className="live-dot" />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {[
            [LayoutDashboard, "Overview"],
            [ShieldAlert, "Incidents"],
            [Search, "Event explorer"],
            [Layers3, "Detection rules"],
            [Activity, "Pipeline health"],
            [Layers3, "Assets"],
            ...(user.role === "administrator"
              ? [[Shield, "Administration"]]
              : []),
          ].map(([Icon, name]) => {
            const Component = Icon as typeof Shield;
            return (
              <button
                key={String(name)}
                className={page === name ? "active" : ""}
                onClick={() => navigate(String(name))}
              >
                <Component size={18} />
                {String(name)}
                {name === "Incidents" && !!dashboard?.open_incidents && (
                  <b>{dashboard.open_incidents}</b>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="lab-card">
            <FlaskConical size={19} />
            <strong>Built to be investigated</strong>
            <p>A controlled security scenario, from event to incident.</p>
            {dashboard?.demo_enabled && user.role === "administrator" && (
              <button onClick={simulate} disabled={busy}>
                Run simulation <ArrowRight size={15} />
              </button>
            )}
          </div>
          <div className="profile">
            <div className="avatar">{user.username[0].toUpperCase()}</div>
            <div>
              {user.username}
              <small>{user.role}</small>
            </div>
            <button
              title="Sign out"
              onClick={async () => {
                try {
                  await api("/auth/logout", { method: "POST" });
                } catch {}
                clearSession();
                setToken("");
                setUser(null);
                setSelected(null);
                setDetail(null);
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            Workspace <ChevronRight size={14} />
            <span>{page}</span>
          </div>
          <div>
            <span className={`live-dot ${error ? "offline" : ""}`} />
            {error
              ? "Connection needs attention"
              : updated
                ? "API connected"
                : "Connecting"}
            <span className="divider" />
            <span className="env-pill">LOCAL</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">SECURITY OPERATIONS</div>
              <h1>{page === "Overview" ? "Your security, in focus." : page}</h1>
              <p>
                {
                  {
                    Overview:
                      "A unified view of your signals, detections, and investigations.",
                    Incidents:
                      "Follow correlated evidence from first signal to resolution.",
                    "Event explorer":
                      "Search normalized telemetry across your monitored services.",
                    "Detection rules":
                      "Version-controlled logic. Explainable results. No black boxes.",
                    "Pipeline health":
                      "Know whether your security platform is keeping up.",
                  }[page]
                }
              </p>
            </div>
            <div className="heading-actions">
              <span className="live-label">
                <span className="live-dot" />
                Polling every 4s
              </span>
              {dashboard?.demo_enabled && user.role === "administrator" && (
                <button className="primary" onClick={simulate} disabled={busy}>
                  <FlaskConical size={16} />
                  {busy ? "Working…" : "Run simulation"}
                </button>
              )}
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              <Check size={16} />
              {notice}
            </div>
          )}
          {page === "Overview" && dashboard && (
            <>
              <div className="stats">
                {[
                  {
                    name: "Open incidents",
                    value: dashboard.open_incidents,
                    icon: ShieldAlert,
                    foot: `${dashboard.critical} critical · ${dashboard.high} high priority`,
                    color: "orange",
                  },
                  {
                    name: "Events ingested",
                    value: dashboard.events,
                    icon: ArrowDownToLine,
                    foot: "Normalized and stored",
                    color: "green",
                  },
                  {
                    name: "Detection alerts",
                    value: dashboard.alerts,
                    icon: Activity,
                    foot: `Across ${dashboard.rules} active rules`,
                    color: "purple",
                  },
                  {
                    name: "Ingestion rate",
                    value: dashboard.events_per_second,
                    icon: Layers3,
                    foot: "Events / second · last 60s",
                    color: "blue",
                  },
                ].map((s) => (
                  <section className="stat" key={s.name}>
                    <div>
                      {s.name}
                      <s.icon size={17} />
                    </div>
                    <strong>
                      {fmt(s.value)}
                      {s.name === "Ingestion rate" && <em> eps</em>}
                    </strong>
                    <small>
                      <span className={`tiny-dot ${s.color}`} />
                      {s.foot}
                    </small>
                  </section>
                ))}
              </div>
              <div className="chart-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h3>Event activity</h3>
                      <p>Received events across all sources</p>
                    </div>
                    <span className="pill">Last 60 minutes</span>
                  </div>
                  <div className="chart">
                    <div className="chart-guides">
                      <span>{Math.max(...dashboard.activity, 1)}</span>
                      <span>
                        {Math.round(Math.max(...dashboard.activity, 1) / 2)}
                      </span>
                      <span>0</span>
                    </div>
                    <div className="bars">
                      {dashboard.activity.map((value, index) => (
                        <div className="bar-track" key={index}>
                          <div
                            title={`${value} events`}
                            style={{
                              height: `${Math.max(value ? 3 : 0, (value / Math.max(...dashboard.activity, 1)) * 100)}%`,
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="chart-axis">
                    <span>60 min ago</span>
                    <span>40 min ago</span>
                    <span>20 min ago</span>
                    <span>Now</span>
                  </div>
                </section>
                <section className="panel sources">
                  <div className="panel-heading">
                    <div>
                      <h3>Monitored services</h3>
                      <p>Event distribution</p>
                    </div>
                    <Layers3 size={17} />
                  </div>
                  {dashboard.services.length ? (
                    dashboard.services.map((s, i) => (
                      <div className="service" key={s.name}>
                        <div>
                          <span>
                            <i className={`tiny-dot ${i ? "blue" : "green"}`} />
                            {s.name}
                          </span>
                          <b>{fmt(s.count)}</b>
                        </div>
                        <div className="service-track">
                          <div
                            style={{
                              width: `${(s.count / dashboard.events) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty compact">
                      <Layers3 size={25} />
                      <p>Services appear as events arrive.</p>
                    </div>
                  )}
                  <div className="source-footer">
                    <span className="live-dot" />
                    Authenticated collectors only
                  </div>
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div className="inline-heading">
                    <h3>Recent incidents</h3>
                    <span className="count">
                      {dashboard.open_incidents} open
                    </span>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => navigate("Incidents")}
                  >
                    View all incidents <ArrowRight size={15} />
                  </button>
                </div>
                {incidentTable}
              </section>
              <div className="bottom-caption">
                <Shield size={14} /> Detection runs independently of AI. Every
                incident starts with evidence.
                <span>Last synced {updated?.toLocaleTimeString()}</span>
              </div>
            </>
          )}
          {page === "Incidents" && (
            <section className="panel">
              <div className="filter-bar">
                <div className="search-input">
                  <Search size={17} />
                  <input
                    aria-label="Search incidents"
                    placeholder="Search incidents, source IP, or service…"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setOffset(0);
                    }}
                  />
                </div>
                <select
                  aria-label="Severity"
                  value={severity}
                  onChange={(e) => {
                    setSeverity(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">All severities</option>
                  {["critical", "high", "medium", "low"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </div>
              {incidentTable}
              <Pagination offset={offset} total={total} change={setOffset} />
            </section>
          )}
          {["Assets", "Administration"].includes(page) && (
            <Operations api={api} page={page} role={user.role} />
          )}
          {page === "Event explorer" && (
            <section className="panel">
              <div className="filter-bar">
                <div className="search-input">
                  <Search size={17} />
                  <input
                    aria-label="Search events"
                    placeholder="Search messages, paths, services or source IP…"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setOffset(0);
                    }}
                  />
                </div>
                <span className="pill">{fmt(total)} events</span>
              </div>
              <div className="filter-bar advanced-filters">
                <label>
                  From
                  <input
                    aria-label="Start time"
                    type="datetime-local"
                    value={startTime}
                    onChange={(e) => {
                      setStartTime(e.target.value);
                      setOffset(0);
                    }}
                  />
                </label>
                <label>
                  To
                  <input
                    aria-label="End time"
                    type="datetime-local"
                    value={endTime}
                    onChange={(e) => {
                      setEndTime(e.target.value);
                      setOffset(0);
                    }}
                  />
                </label>
                <label>
                  Request ID
                  <input
                    aria-label="Request ID"
                    value={requestId}
                    onChange={(e) => {
                      setRequestId(e.target.value);
                      setOffset(0);
                    }}
                  />
                </label>
                <span className="pill">{searchBackend}</span>
                {canEdit && (
                  <button
                    onClick={async () => {
                      try {
                        const response = await request(
                          "/events/export?q=" + encodeURIComponent(query),
                        );
                        const url = URL.createObjectURL(await response.blob());
                        const anchor = document.createElement("a");
                        anchor.href = url;
                        anchor.download = "sentinel-events.csv";
                        anchor.click();
                        URL.revokeObjectURL(url);
                      } catch (e) {
                        setError((e as Error).message);
                      }
                    }}
                  >
                    Export up to 1,000
                  </button>
                )}
              </div>
              <div className="event-list">
                {events.map((e) => (
                  <details key={e.event_id}>
                    <summary>
                      <span className="mono muted">{time(e.timestamp)}</span>
                      <span className="event-type">{label(e.event_type)}</span>
                      <span className="mono">{e.source_ip || "—"}</span>
                      <span>{e.service}</span>
                      <ChevronRight size={15} />
                    </summary>
                    <pre>{JSON.stringify(e, null, 2)}</pre>
                  </details>
                ))}
                {!events.length && (
                  <div className="empty">
                    <Search size={30} />
                    <h3>No matching events</h3>
                    <p>Ingest telemetry or run the lab to begin exploring.</p>
                  </div>
                )}
              </div>
              <Pagination offset={offset} total={total} change={setOffset} />
            </section>
          )}
          {page === "Detection rules" && (
            <section className="panel">
              <div className="panel-heading">
                <h3>
                  Detection library{" "}
                  <span className="count">{rules.length} rules</span>
                </h3>
                <span className="pill">Managed in Git</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>RULE</th>
                      <th>SEVERITY</th>
                      <th>THRESHOLD</th>
                      <th>ATT&CK MAPPING</th>
                      <th>STATE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map((r) => (
                      <tr key={r.id}>
                        <td>
                          {r.name}
                          <small className="mono">{r.id}</small>
                        </td>
                        <td>
                          <span className={`badge ${r.severity}`}>
                            <i />
                            {r.severity}
                          </span>
                        </td>
                        <td className="muted">
                          {r.count === 1
                            ? "Single event / sequence"
                            : `${r.count} events in ${r.within_seconds}s`}
                        </td>
                        <td>
                          {r.mitre ? (
                            <a
                              className="mitre-link"
                              href={`https://attack.mitre.org/techniques/${r.mitre.id}/`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {r.mitre.id}
                              <small>{r.mitre.tactic}</small>
                            </a>
                          ) : (
                            <span className="muted">Operational signal</span>
                          )}
                        </td>
                        <td>
                          {user.role === "administrator" ? (
                            <button
                              aria-label={`Toggle ${r.id}`}
                              onClick={() =>
                                void mutate(`/rules/${r.id}`, "PATCH", {
                                  enabled: !r.enabled,
                                })
                              }
                            >
                              {r.enabled ? "Enabled" : "Disabled"}
                            </button>
                          ) : (
                            <span className="enabled">
                              {r.enabled ? "Enabled" : "Disabled"}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {page === "Pipeline health" && dashboard && (
            <>
              <IntegrationHealth api={api} />
              <div className="pipeline-cards">
                {[
                  {
                    title: "Ingestion API",
                    value: "Connected",
                    description: "API key protected · 512 KiB body limit",
                    icon: ArrowDownToLine,
                  },
                  {
                    title: "Processing queue",
                    value: `${dashboard.queued} pending`,
                    description: dashboard.queue_backend,
                    icon: Layers3,
                  },
                  {
                    title: "Dead-letter queue",
                    value: `${dashboard.dead_letters} failed`,
                    description: "Admin API supports inspection and replay",
                    icon: ShieldAlert,
                  },
                  {
                    title: "Enrichment",
                    value: "Playbook mode",
                    description: "Deterministic guidance · AI not connected",
                    icon: FileText,
                  },
                ].map((c) => (
                  <section className="panel health-card" key={c.title}>
                    <c.icon size={24} />
                    <h3>{c.title}</h3>
                    <strong>{c.value}</strong>
                    <p>{c.description}</p>
                  </section>
                ))}
              </div>
              <section className="panel health-explainer">
                <h3>From telemetry to an investigation</h3>
                <div className="flow">
                  {[
                    "Authenticate",
                    "Queue",
                    "Normalize",
                    "Detect",
                    "Correlate",
                    "Investigate",
                  ].map((s, i) => (
                    <React.Fragment key={s}>
                      <div>
                        <small>0{i + 1}</small>
                        {s}
                      </div>
                      {i < 5 && <ArrowRight size={16} />}
                    </React.Fragment>
                  ))}
                </div>
                <p>
                  Accepted events are committed to the database before the API
                  responds. The worker processes evidence in a separate
                  transaction, and retries failures before moving them to the
                  dead-letter queue.
                </p>
                <p>
                  Queue counts reflect persisted state. A connected API does not
                  prove worker health; a growing queue means processing needs
                  attention.
                </p>
              </section>
            </>
          )}
          <footer>
            SentinelAI <span>Security observability platform</span>
            <span className="footer-right">
              LOCAL LAB <span> / </span> v0.2.0
            </span>
          </footer>
        </main>
      </div>
      {selected && (
        <div
          className="drawer-backdrop"
          onClick={() => {
            setSelected(null);
            setDetail(null);
          }}
        >
          <section
            className="drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Incident investigation"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-top">
              <span>
                <ShieldAlert size={18} /> INCIDENT INVESTIGATION
              </span>
              <button
                aria-label="Close incident"
                onClick={() => {
                  setSelected(null);
                  setDetail(null);
                }}
              >
                <X size={20} />
              </button>
            </div>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {!detail ? (
              <div className="empty">Loading evidence…</div>
            ) : (
              <>
                <div className="drawer-title">
                  <span className={`badge ${detail.severity}`}>
                    <i />
                    {detail.severity}
                  </span>
                  <span className="mono muted">
                    INC-{detail.id.slice(0, 8).toUpperCase()}
                  </span>
                  <h2>{detail.title}</h2>
                  <p>
                    {detail.service} <span> / </span>{" "}
                    <span className="mono">{detail.source_ip}</span>
                  </p>
                </div>
                <div className="detail-meta">
                  <div>
                    <small>STATUS</small>
                    <strong>{label(detail.status)}</strong>
                  </div>
                  <div>
                    <small>OWNER</small>
                    <strong>{detail.owner || "Unassigned"}</strong>
                  </div>
                  <div>
                    <small>EVIDENCE</small>
                    <strong>{detail.evidence_count} events</strong>
                  </div>
                </div>
                {canEdit && (
                  <div className="investigation-controls">
                    <label>
                      Status
                      <select
                        aria-label="Status"
                        value={detail.status}
                        onChange={(e) =>
                          void mutate(`/incidents/${detail.id}`, "PATCH", {
                            status: e.target.value,
                            ...(resolution ? { resolution } : {}),
                          })
                        }
                      >
                        {[
                          "NEW",
                          "ACKNOWLEDGED",
                          "INVESTIGATING",
                          "MITIGATED",
                          "RESOLVED",
                          "FALSE_POSITIVE",
                        ].map((s) => (
                          <option key={s} value={s}>
                            {label(s)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void mutate(`/incidents/${detail.id}`, "PATCH", {
                          owner: user.username,
                        })
                      }
                    >
                      Assign to me
                    </button>
                    <label className="resolution">
                      Resolution (required before closing)
                      <input
                        value={resolution}
                        onChange={(e) => setResolution(e.target.value)}
                        placeholder="Record your findings and remediation…"
                      />
                    </label>
                  </div>
                )}
                <div className="detail-section">
                  <h3>
                    <Layers3 size={17} /> Related detections
                  </h3>
                  {detail.alerts.map((a) => (
                    <div className="alert-item" key={a.id}>
                      <div>
                        <span className="mono muted">{a.rule_id}</span>
                        <strong>{a.title}</strong>
                      </div>
                      {a.mitre && (
                        <a
                          className="pill"
                          href={`https://attack.mitre.org/techniques/${a.mitre.id}/`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {a.mitre.id}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
                <div className="assessment detail-section">
                  <div className="eyebrow">INVESTIGATION ASSISTANT</div>
                  {canEdit && (
                    <button
                      disabled={busy || !dashboard?.ai_enabled}
                      onClick={() =>
                        void mutate(
                          `/incidents/${detail.id}/analysis`,
                          "POST",
                          {},
                        )
                      }
                    >
                      {dashboard?.ai_enabled
                        ? "Request AI assessment"
                        : "AI not configured"}
                    </button>
                  )}
                  <h3>Start with the evidence.</h3>
                  <span className="assessment-label">
                    {detail.analysis.label}
                  </span>
                  <p>{detail.analysis.summary}</p>
                  <h4>Recommended investigation</h4>
                  <ol>
                    {detail.analysis.investigation_steps.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ol>
                  <div className="read-only">
                    <CircleHelp size={14} />
                    Guidance only. No automated response actions.
                  </div>
                </div>
                <div className="detail-section">
                  <h3>
                    <Clock3 size={17} /> Evidence timeline{" "}
                    <span className="count">{detail.events.length} shown</span>
                  </h3>
                  <div className="timeline">
                    {detail.events.map((e) => (
                      <div key={e.event_id}>
                        <span
                          className={`timeline-dot ${e.event_type === "authentication_success" ? "highlight" : ""}`}
                        />
                        <span className="mono muted">{time(e.timestamp)}</span>
                        <strong>{label(e.event_type)}</strong>
                        <p>
                          {e.message}
                          {e.http_path && (
                            <code>
                              {e.http_path} · {e.status_code}
                            </code>
                          )}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="detail-section">
                  <h3>
                    <FileText size={17} /> Analyst notes
                  </h3>
                  {detail.notes.map((n) => (
                    <div className="note" key={n.id}>
                      <strong>
                        {n.author}
                        <small>{time(n.created_at)}</small>
                      </strong>
                      <p>{n.body}</p>
                    </div>
                  ))}
                  {!detail.notes.length && (
                    <p className="muted">
                      No notes yet. Keep your investigation trail here.
                    </p>
                  )}
                  {canEdit && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        void mutate(`/incidents/${detail.id}/notes`, "POST", {
                          body: note,
                        });
                      }}
                    >
                      <textarea
                        aria-label="Analyst note"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="Add evidence, observations, or next steps…"
                        required
                        maxLength={4000}
                      />
                      <button
                        className="primary"
                        disabled={busy || !note.trim()}
                      >
                        Add note <ArrowRight size={14} />
                      </button>
                    </form>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
function Pagination({
  offset,
  total,
  change,
}: {
  offset: number;
  total: number;
  change: (n: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + 50, total)} of ${fmt(total)}`
          : "0 results"}
      </span>
      <button disabled={!offset} onClick={() => change(offset - 50)}>
        Previous
      </button>
      <button
        disabled={offset + 50 >= total}
        onClick={() => change(offset + 50)}
      >
        Next
      </button>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
