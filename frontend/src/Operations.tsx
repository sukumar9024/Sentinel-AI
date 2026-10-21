import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

type Api = (path: string, options?: RequestInit) => Promise<any>;
type Row = Record<string, any>;
export function Operations({
  api,
  page,
  role,
}: {
  api: Api;
  page: string;
  role: string;
}) {
  const [rows, setRows] = useState<Row[]>([]),
    [tab, setTab] = useState("users"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const endpoint = page === "Assets" ? "assets" : tab;
  const load = useCallback(async () => {
    try {
      setRows((await api("/" + endpoint)).items);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [api, endpoint]);
  useEffect(() => {
    void load();
  }, [load]);
  async function mutate(path: string, method: string, body?: object) {
    setBusy(true);
    try {
      await api(path, {
        method,
        body: body ? JSON.stringify(body) : undefined,
      });
      setNotice("Saved. The action is recorded in the audit log.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    void mutate(
      "/" + endpoint,
      "POST",
      Object.fromEntries(new FormData(form)),
    ).then(() => form.reset());
  }
  return (
    <>
      <div className="panel ops-panel">
        {page === "Administration" && (
          <div className="ops-tabs">
            {["users", "audit", "dlq", "tasks"].map((t) => (
              <button
                key={t}
                className={tab === t ? "primary" : ""}
                onClick={() => {
                  setTab(t);
                  setNotice("");
                }}
              >
                {
                  {
                    users: "Users",
                    audit: "Audit trail",
                    dlq: "Dead letters",
                    tasks: "Integration deliveries",
                  }[t]
                }
              </button>
            ))}
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="notice" role="status">
            {notice}
          </div>
        )}
        {role === "administrator" && endpoint === "assets" && (
          <form className="ops-form" onSubmit={submit}>
            <h3>Register an asset</h3>
            {["host", "service", "owner"].map((k) => (
              <label key={k}>
                {k}
                <input name={k} required maxLength={100} />
              </label>
            ))}
            <label>
              Environment
              <select name="environment">
                {["local", "dev", "staging", "production"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label>
              Criticality
              <select name="criticality">
                {["low", "medium", "high", "critical"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <button className="primary" disabled={busy}>
              Save asset
            </button>
          </form>
        )}
        {endpoint === "users" && (
          <form className="ops-form" onSubmit={submit}>
            <h3>Create a platform user</h3>
            <label>
              Username
              <input
                name="username"
                required
                pattern="[a-zA-Z0-9_.@-]{1,100}"
              />
            </label>
            <label>
              Initial password
              <input
                name="password"
                type="password"
                required
                minLength={12}
                autoComplete="new-password"
              />
            </label>
            <label>
              Role
              <select name="role">
                {["viewer", "analyst", "administrator"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <button className="primary" disabled={busy}>
              Create user
            </button>
          </form>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {(endpoint === "assets"
                  ? ["HOST / SERVICE", "ENVIRONMENT", "OWNER", "CRITICALITY"]
                  : endpoint === "users"
                    ? ["USERNAME", "ROLE", "ACCESS", "ACTION"]
                    : endpoint === "audit"
                      ? ["WHEN", "ACTOR", "ACTION", "TARGET"]
                      : ["ID / TYPE", "STATE", "ATTEMPTS", "ERROR", "ACTION"]
                ).map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.id || row.username || i}>
                  {endpoint === "assets" ? (
                    <>
                      <td>
                        {row.host}
                        <small>{row.service}</small>
                      </td>
                      <td>{row.environment}</td>
                      <td>{row.owner}</td>
                      <td>
                        <span className={"badge " + row.criticality}>
                          {row.criticality}
                        </span>
                      </td>
                    </>
                  ) : endpoint === "users" ? (
                    <>
                      <td>{row.username}</td>
                      <td>{row.role}</td>
                      <td>{row.enabled ? "Enabled" : "Disabled"}</td>
                      <td>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void mutate("/users/" + row.username, "PATCH", {
                              enabled: !row.enabled,
                            })
                          }
                        >
                          {row.enabled ? "Disable" : "Enable"}
                        </button>
                      </td>
                    </>
                  ) : endpoint === "audit" ? (
                    <>
                      <td>{new Date(row.created_at + "Z").toLocaleString()}</td>
                      <td>{row.actor}</td>
                      <td>{row.action}</td>
                      <td className="mono">{row.target}</td>
                    </>
                  ) : (
                    <>
                      <td className="mono">
                        {row.id.slice(0, 12)}
                        <small>{row.kind || "ingestion"}</small>
                      </td>
                      <td>{row.state}</td>
                      <td>{row.attempts}</td>
                      <td>{row.error || "—"}</td>
                      <td>
                        {["dead", "disabled"].includes(row.state) && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              void mutate(
                                "/" + endpoint + "/" + row.id + "/replay",
                                "POST",
                              )
                            }
                          >
                            Replay
                          </button>
                        )}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && <div className="empty">No records yet.</div>}
        <p className="ops-hint">
          Showing up to {endpoint === "assets" ? 100 : 50} records. Detailed
          history and pagination are available through the API.
        </p>
      </div>
    </>
  );
}
export function IntegrationHealth({ api }: { api: Api }) {
  const [data, setData] = useState<Row | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await api("/platform");
        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    void load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [api]);
  return (
    <section className="panel ops-panel">
      <h3>Workers and integration deliveries</h3>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <div className="ops-tabs">
            <span className="pill">
              Search{" "}
              {data.search_enabled
                ? "connected configuration"
                : "database mode"}
            </span>
            <span className="pill">
              AI {data.ai_enabled ? "enabled" : "disabled"}
            </span>
            <span className="pill">
              Notifications{" "}
              {data.notifications_enabled ? "enabled" : "disabled"}
            </span>
          </div>
          {data.workers.length ? (
            data.workers.map((w: Row) => (
              <p className="worker-line" key={w.name}>
                <span className={"live-dot " + (w.healthy ? "" : "offline")} />
                <code>{w.name}</code>
                <span>
                  {w.healthy ? "Recent heartbeat" : "Stale heartbeat"}
                </span>
              </p>
            ))
          ) : (
            <p className="muted">
              No worker heartbeat recorded. Start the workers to process queued
              events.
            </p>
          )}
          <div className="ops-tabs">
            {data.integrations.map((s: Row) => (
              <span className="pill" key={s.kind + s.state}>
                {s.kind} · {s.state}: {s.count}
              </span>
            ))}
          </div>
          <p className="ops-hint">
            AI uses a separately configured local Ollama model. Disabled
            integrations retain their tasks for replay. Detection continues
            independently.
          </p>
        </>
      )}
    </section>
  );
}
