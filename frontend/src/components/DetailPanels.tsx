import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { VisEdge } from "../state/graphState";
import type { Category, PathNode } from "../types/api";
import { hostname, initials, kindEncoding, plural } from "../utils/format";
import { EdgeProvenance } from "./Provenance";
import { Swatch } from "./Swatch";

const SOURCE_LINK_TYPES = ["wikidata", "discogs", "allmusic", "official homepage"];

function Loading({ what }: { what: string }) {
  return <div className="panel-body muted">Loading {what}…</div>;
}

interface ArtistPanelProps {
  id: string;
  neighbors: { edge: VisEdge; otherId: string; otherName: string }[];
  truncated?: { shown: number; total: number };
  onExpand: (id: string) => void;
  onRecenter: (id: string) => void;
  onSelectEdge: (a: string, b: string) => void;
  onConnect: (node: PathNode, end: "from" | "to") => void;
}

export function ArtistPanel({ id, neighbors, truncated, onExpand, onRecenter, onSelectEdge, onConnect }: ArtistPanelProps) {
  const { data, error, loading } = useApi(id, (signal) => api.artist(id, signal));
  if (loading && !data) return <Loading what="artist" />;
  if (error) return <div className="panel-body error">{error.message}</div>;
  if (!data) return null;

  const node: PathNode = { id: data.id, name: data.name, genres: data.genres.map((g) => g.name) };
  const strongest = [...neighbors].sort((x, y) => y.edge.strength - x.edge.strength).slice(0, 10);
  const maxStrength = strongest[0]?.edge.strength ?? 1;
  const maxConnections = Math.max(1, ...data.connections.map((c) => c.artists));
  const subtitle = [data.artist_type, data.country, data.begin_date ? `since ${data.begin_date.slice(0, 4)}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="panel-body">
      <header className="entity-header">
        <span className="avatar" aria-hidden="true">
          {initials(data.name)}
        </span>
        <div className="titles">
          <h2>{data.name}</h2>
          <span className="subtitle">{[subtitle, data.disambiguation].filter(Boolean).join(" — ")}</span>
        </div>
      </header>
      {!data.hydrated && (
        <p className="callout">Known from credits on other artists' releases. Their own discography isn't loaded.</p>
      )}
      {data.genres.length > 0 && (
        <div className="chips">
          {data.genres.slice(0, 6).map((g) => (
            <span key={g.name} className="chip">
              {g.name}
            </span>
          ))}
        </div>
      )}
      <div className="actions">
        <button type="button" className="btn" onClick={() => onExpand(data.id)}>
          Expand
        </button>
        <button type="button" className="btn" onClick={() => onRecenter(data.id)}>
          Center here
        </button>
        <button type="button" className="btn" onClick={() => onConnect(node, "from")}>
          Connect from
        </button>
        <button type="button" className="btn" onClick={() => onConnect(node, "to")}>
          Connect to
        </button>
      </div>

      <section className="section">
        <h3>{plural(data.degree, "connected artist")}</h3>
        <ul className="bar-list">
          {data.connections.map((c) => {
            const enc = kindEncoding(c.kind);
            return (
              <li key={c.kind} className="bar-row">
                <span className="label">
                  <Swatch encoding={enc} />
                  <span>{c.label}</span>
                </span>
                <span className="value">{c.artists}</span>
                <span className="bar-track" aria-hidden="true">
                  <span
                    className="bar-fill"
                    style={{ display: "block", width: `${(100 * c.artists) / maxConnections}%`, background: enc.color }}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      {strongest.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h3>Strongest links</h3>
            <span className="meta">strength</span>
          </div>
          <ul className="bar-list">
            {strongest.map(({ edge, otherId, otherName }) => (
              <li key={edge.key} className="bar-row">
                <span className="label">
                  <button type="button" className="link-btn plain" onClick={() => onSelectEdge(id, otherId)}>
                    {otherName}
                  </button>
                </span>
                <span className="value">{edge.strength.toFixed(1)}</span>
                <span className="bar-track" aria-hidden="true">
                  <span
                    className="bar-fill"
                    style={{
                      display: "block",
                      width: `${(100 * edge.strength) / maxStrength}%`,
                      background: "var(--neutral-strong)",
                    }}
                  />
                </span>
              </li>
            ))}
          </ul>
          {truncated && truncated.total > truncated.shown && (
            <p className="note">
              The graph shows {truncated.shown} of {truncated.total} connections. Raise “Neighbors per artist” to see more.
            </p>
          )}
        </section>
      )}

      {data.albums.length > 0 && (
        <section className="section">
          <h3>Albums in the dataset</h3>
          <ul className="plain-list rows">
            {data.albums.map((a) => (
              <li key={a.id}>
                <span>{a.title}</span>
                <span>{a.year}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.aliases.length > 0 && (
        <section className="section">
          <h3>Also known as</h3>
          <p className="small muted">
            {data.aliases
              .slice(0, 10)
              .map((a) => a.alias)
              .join(" · ")}
          </p>
        </section>
      )}

      <section className="section">
        <h3>Sources</h3>
        <ul className="plain-list small">
          {data.source_urls.map((u) => (
            <li key={u}>
              <a href={u} target="_blank" rel="noreferrer">
                {hostname(u)} · canonical record
              </a>
            </li>
          ))}
          {data.links
            .filter((l) => SOURCE_LINK_TYPES.includes(l.link_type))
            .map((l) => (
              <li key={l.url}>
                <a href={l.url} target="_blank" rel="noreferrer">
                  {l.link_type}
                </a>
              </li>
            ))}
        </ul>
      </section>
    </div>
  );
}

interface EdgePanelProps {
  a: string;
  b: string;
  categories: Category[];
  onSelectArtist: (id: string) => void;
}

export function EdgePanel({ a, b, categories, onSelectArtist }: EdgePanelProps) {
  const key = `${a}|${b}|${categories.join(",")}`;
  const { data, error, loading } = useApi(key, (signal) => api.edge(a, b, categories, signal));
  if (loading && !data) return <Loading what="evidence" />;
  if (error) return <div className="panel-body error">{error.message}</div>;
  if (!data) return null;
  return (
    <div className="panel-body">
      <header className="panel-intro">
        <h3>Connection</h3>
        <h2>
          <button type="button" className="link-btn plain" onClick={() => onSelectArtist(data.a.id)}>
            {data.a.name}
          </button>{" "}
          <span className="muted">↔</span>{" "}
          <button type="button" className="link-btn plain" onClick={() => onSelectArtist(data.b.id)}>
            {data.b.name}
          </button>
        </h2>
        <p className="meta">
          {plural(data.evidence.length, "piece")} of evidence · strength {data.strength.toFixed(2)}
        </p>
      </header>
      <ul className="evidence-list">
        {data.evidence.map((e) => (
          <li key={`${e.kind}:${e.subject_id}:${e.sentence}`}>
            <Swatch encoding={kindEncoding(e.kind)} title={e.kind_label} />
            <span>{e.sentence}</span>
          </li>
        ))}
      </ul>
      <EdgeProvenance a={a} b={b} />
    </div>
  );
}

interface TrackPanelProps {
  id: string;
  onOpenArtist: (id: string) => void;
}

export function TrackPanel({ id, onOpenArtist }: TrackPanelProps) {
  const { data, error, loading } = useApi(id, (signal) => api.track(id, signal));
  if (loading && !data) return <Loading what="track" />;
  if (error) return <div className="panel-body error">{error.message}</div>;
  if (!data) return null;
  const byRole = new Map<string, typeof data.credits>();
  for (const credit of data.credits) byRole.set(credit.role, [...(byRole.get(credit.role) ?? []), credit]);
  const length = data.length_ms
    ? `${Math.floor(data.length_ms / 60000)}:${String(Math.round((data.length_ms % 60000) / 1000)).padStart(2, "0")}`
    : null;
  return (
    <div className="panel-body">
      <header className="panel-intro">
        <h3>Track</h3>
        <h2>{data.title}</h2>
        <p className="meta">
          {[...data.albums.map((a) => `${a.title}${a.year ? ` (${a.year})` : ""}`), length].filter(Boolean).join(" · ")}
        </p>
      </header>
      {[...byRole.entries()].map(([role, credits]) => (
        <section className="section" key={role}>
          <h3>{role}</h3>
          <ul className="plain-list">
            {credits.map((c) => (
              <li key={`${c.artist_id}:${c.role_detail}`}>
                <button type="button" className="link-btn plain" onClick={() => onOpenArtist(c.artist_id)}>
                  {c.artist_name}
                </button>
                {c.role_detail && <span className="muted"> ({c.role_detail})</span>}
                {c.credited_as && c.credited_as !== c.artist_name && <span className="muted"> as “{c.credited_as}”</span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <section className="section">
        <h3>Sources</h3>
        <ul className="plain-list small">
          {data.source_urls.map((u) => (
            <li key={u}>
              <a href={u} target="_blank" rel="noreferrer">
                {hostname(u)} · recording
              </a>
            </li>
          ))}
        </ul>
        {data.source_urls.length > 1 && (
          <p className="note">Several source recordings (e.g. remasters) were merged into this one song.</p>
        )}
      </section>
    </div>
  );
}
